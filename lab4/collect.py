"""Лабораторная 4. Сбор товаров кнопкой Load more и через AJAX."""
import argparse
import csv
import json
import os
import random
import re
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psutil
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.scrapingcourse.com/button-click"
AJAX = "https://www.scrapingcourse.com/ajax/products"
USER_AGENT = "UniversityLab4/1.0 (educational training-site study)"
CARD = "#product-grid .product-item"
COLUMNS = ["product_id", "name", "price", "currency", "product_url"]
LOG_COLUMNS = ["run", "method", "iteration", "items", "unique_items", "growth", "seconds", "timestamp", "url", "status", "error"]
EXTRACT = """cards => cards.map(card => ({
    name: card.querySelector('.product-name')?.textContent || '',
    price: card.querySelector('.product-price')?.textContent || '',
    product_url: card.querySelector('a[href]')?.href || ''
}))"""


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    folder = path.parent.parent if path.parent.name in {"artifacts", "nocode"} else path.parent
    folder.mkdir(parents=True, exist_ok=True)
    result_file = folder / "results.json"
    results = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
    results[path.relative_to(folder).as_posix()] = data
    result_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def append_log(folder, **row):
    path = Path(folder) / "collection_log.csv"
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=LOG_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in LOG_COLUMNS})


class PeakMemory:
    """Пиковая сумма RSS процесса Python и его дочерних процессов, шаг 0,1 с."""
    def __init__(self):
        self.peak = 0
        self.stop = threading.Event()

    def sample(self):
        process = psutil.Process()
        while not self.stop.is_set():
            total = 0
            for item in [process] + process.children(recursive=True):
                try:
                    total += item.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue  # Процесс браузера мог завершиться между двумя измерениями.
            self.peak = max(self.peak, total)
            self.stop.wait(0.1)

    def __enter__(self):
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()


def normalize(records):
    table = pd.DataFrame(records, columns=["name", "price", "product_url"])
    table["name"] = table["name"].fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    table["product_url"] = table["product_url"].fillna("").str.strip().str.rstrip("/")
    table["product_id"] = table["product_url"].str.rsplit("/", n=1).str[-1]
    table["price"] = pd.to_numeric(table["price"].astype(str).str.replace(r"[^0-9.]", "", regex=True), errors="coerce")
    table["currency"] = "USD"
    return table[COLUMNS].drop_duplicates("product_id").sort_values("product_id").reset_index(drop=True)


def smoke_check(table, threshold=0.05):
    required = ["product_id", "name", "price", "product_url"]
    missing = table[required].isna() | table[required].astype(str).apply(lambda col: col.str.strip().eq(""))
    fraction = float(missing.any(axis=1).mean()) if len(table) else 1.0
    result = {"records": len(table), "empty_required_fraction": fraction,
              "empty_by_field": missing.sum().astype(int).to_dict(),
              "duplicates": int(table.duplicated("product_id").sum()),
              "nonpositive_prices": int(table["price"].le(0).sum()),
              "price_type": str(table["price"].dtype), "warning": fraction > threshold}
    print("ПРЕДУПРЕЖДЕНИЕ: слишком много пустых полей" if result["warning"] else "Smoke-check: обязательные поля заполнены")
    if table.empty or result["duplicates"] or result["nonpositive_prices"]:
        raise ValueError(f"Ошибка качества данных: {result}")
    return result


def browser_options():
    options = {"headless": True}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        options["proxy"] = {"server": proxy}
    return options


def save_failure(page, folder, label):
    folder = Path(folder) / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f"{label}.png"), full_page=False, timeout=10000)
    (folder / f"{label}.html").write_text(page.content(), encoding="utf-8")


def collect_browser(folder, *, block_resources=True, max_records=300, max_iterations=30,
                    stagnant_limit=2, max_clicks=None, pause=0.7, extraction_test=False,
                    method="browser", keep_html=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    run = now()
    started = time.perf_counter()
    counts = {"requests_started": 0, "responses": 0, "body_bytes": 0, "wire_bytes": 0, "blocked": 0}
    raw, network, extraction = [], [], {}
    clicks = 0
    timeouts = 0
    reason = "max_iterations"
    html = ""
    with PeakMemory() as memory, sync_playwright() as p:
        browser = p.chromium.launch(**browser_options())
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width":1280,"height":900}, locale="en-US")
        context.set_default_timeout(15000)
        context.set_default_navigation_timeout(30000)
        try:
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            def request_event(event):
                counts["requests_started"] += 1
            def response_event(event):
                counts["responses"] += 1
            def data_event(event):
                counts["body_bytes"] += event["dataLength"]
            def finished_event(event):
                counts["wire_bytes"] += event["encodedDataLength"]
            cdp.on("Network.requestWillBeSent", request_event)
            cdp.on("Network.responseReceived", response_event)
            cdp.on("Network.dataReceived", data_event)
            cdp.on("Network.loadingFinished", finished_event)
            def route_request(route):
                if block_resources and route.request.resource_type in {"image", "font", "media"}:
                    counts["blocked"] += 1
                    route.abort()
                else:
                    route.continue_()
            if block_resources:
                page.route("**/*", route_request)
            response = page.goto(URL, wait_until="load")
            page.locator(CARD).first.wait_for(state="visible")
            raw = page.locator(CARD).evaluate_all(EXTRACT)
            table = normalize(raw)
            append_log(folder, run=run, method=method, iteration=0, items=len(raw), unique_items=len(table),
                       growth=len(table), seconds=round(time.perf_counter()-started,4), timestamp=now(), url=URL, status=response.status)
            stale = 0
            for iteration in range(1, max_iterations + 1):
                if len(table) >= max_records:
                    reason = "max_records"
                    break
                if max_clicks is not None and clicks >= max_clicks:
                    reason = "requested_clicks"
                    break
                button = page.get_by_test_id("load-more-btn")
                if not button.is_visible():
                    reason = "button_hidden"
                    break
                before = len(table)
                visible_before = len(raw)
                tick = time.perf_counter()
                time.sleep(pause)  # Только пауза вежливости; готовность данных проверяется ниже.
                try:
                    with page.expect_response(lambda r: urlparse(r.url).path == "/ajax/products") as response_info:
                        button.click()
                    fetched = response_info.value
                    clicks += 1
                    if not fetched.ok:
                        raise RuntimeError(f"AJAX вернул HTTP {fetched.status}")
                    page.wait_for_function("""n => document.querySelectorAll('#product-grid .product-item').length > n
                        || getComputedStyle(document.querySelector('[data-testid="load-more-btn"]')).display === 'none'""", arg=visible_before)
                    raw = page.locator(CARD).evaluate_all(EXTRACT)
                    table = normalize(raw)
                    growth = len(table) - before
                    stale = stale + 1 if growth == 0 else 0
                    network.append({"url": fetched.url, "method": fetched.request.method,
                                    "status": fetched.status, "content_type": fetched.headers.get("content-type", "")})
                    append_log(folder, run=run, method=method, iteration=iteration, items=len(raw), unique_items=len(table),
                               growth=growth, seconds=round(time.perf_counter()-tick,4), timestamp=now(), url=fetched.url, status=fetched.status)
                except PlaywrightTimeoutError as error:
                    timeouts += 1
                    stale += 1
                    save_failure(page, folder, f"timeout_{method}_{iteration}")
                    append_log(folder, run=run, method=method, iteration=iteration, items=len(raw), unique_items=len(table),
                               growth=0, seconds=round(time.perf_counter()-tick,4), timestamp=now(), url=page.url, error=str(error)[:250])
                    print(f"Таймаут на итерации {iteration}; сохранены HTML и скриншот")
                if stale >= stagnant_limit:
                    reason = "no_growth"
                    break
            page.wait_for_function("Array.from(document.images).every(image => image.complete)")
            collection_seconds = time.perf_counter() - started
            if keep_html:
                html = page.content()
            if extraction_test:
                tick = time.perf_counter()
                bulk = page.locator(CARD).evaluate_all(EXTRACT)
                bulk_seconds = time.perf_counter() - tick
                tick = time.perf_counter()
                individual = []
                for card in page.locator(CARD).all():
                    individual.append({"name": card.locator(".product-name").inner_text(),
                                       "price": card.locator(".product-price").inner_text(),
                                       "product_url": card.locator("a[href]").get_attribute("href")})
                individual_seconds = time.perf_counter() - tick
                pd.testing.assert_frame_equal(normalize(bulk), normalize(individual))
                extraction = {"raw_cards":len(bulk), "bulk_seconds":bulk_seconds,
                              "individual_seconds":individual_seconds, "speedup":individual_seconds/bulk_seconds}
        except PlaywrightTimeoutError:
            save_failure(page, folder, f"timeout_{method}_page")
            raise
        finally:
            context.close()
            browser.close()
    table = table.head(max_records)
    metrics = {"method":method, "records":len(table), "raw_cards":len(raw), "removed_duplicates":len(raw)-len(normalize(raw)),
               "clicks":clicks, "timeouts":timeouts, "stop_reason":reason, "seconds":round(collection_seconds,4),
               "total_seconds_with_checks":round(time.perf_counter()-started,4),
               "network_requests":counts["requests_started"]-counts["blocked"], **counts,
               "traffic_mb":round(counts["body_bytes"]/1_000_000,6), "peak_memory_mb":round(memory.peak/1_000_000,3),
               "block_resources":block_resources, "started_at":run, "finished_at":now(), "xhr":network, "extraction":extraction}
    return table, metrics, html


def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for card in soup.select(".product-item"):
        name, price, anchor = card.select_one(".product-name"), card.select_one(".product-price"), card.select_one("a[href]")
        records.append({"name":name.get_text() if name else "", "price":price.get_text() if price else "",
                        "product_url":anchor.get("href", "") if anchor else ""})
    return records


def collect_light(folder, *, max_records=300, max_pages=30, stagnant_limit=2, max_clicks=None, pause=0.7, method="light"):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    run = now()
    started = time.perf_counter()
    raw, request_count, body_bytes, stale, pages = [], 0, 0, 0, 0
    reason = "max_pages"
    with PeakMemory() as memory, requests.Session() as session:
        session.headers.update({"User-Agent":USER_AGENT, "Accept":"text/html", "Accept-Encoding":"identity"})
        offset = None
        for iteration in range(max_pages):
            if max_clicks is not None and iteration > max_clicks:
                reason = "requested_clicks"
                break
            if iteration:
                time.sleep(pause)
            url, params = (URL, None) if iteration == 0 else (AJAX, {"offset":offset})
            before = len(normalize(raw))
            tick = time.perf_counter()
            for attempt in range(3):
                response = session.get(url, params=params, timeout=(5,25))
                request_count += 1
                body_bytes += len(response.content)
                if response.status_code != 429 and response.status_code < 500:
                    response.raise_for_status()
                    break
                if attempt == 2:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After", "0")
                try:
                    server_delay = float(retry_after)
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    server_delay = max(0, (parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds())
                time.sleep(max(server_delay, 2**attempt + random.uniform(0,0.25)))
            if response.status_code == 204:
                batch = []
            else:
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise ValueError(f"Ожидался HTML: {response.content[:200]!r}")
                batch = parse_cards(response.text)
            raw.extend(batch)
            table = normalize(raw)
            growth = len(table)-before
            pages += 1
            append_log(folder, run=run, method=method, iteration=iteration, items=len(raw), unique_items=len(table), growth=growth,
                       seconds=round(time.perf_counter()-tick,4), timestamp=now(), url=response.url, status=response.status_code)
            if iteration == 0:
                offset = int(BeautifulSoup(response.text,"html.parser").select_one("[data-testid='load-more-btn']")["data-offset"])
            else:
                offset += 10
            stale = stale+1 if growth == 0 else 0
            if not batch:
                reason = "empty_response"
                break
            if len(table) >= max_records:
                reason = "max_records"
                break
            if stale >= stagnant_limit:
                reason = "no_growth"
                break
    seconds = time.perf_counter()-started
    table = table.head(max_records)
    metrics = {"method":method, "records":len(table), "raw_cards":len(raw), "removed_duplicates":len(raw)-len(normalize(raw)),
               "pages":pages, "seconds":round(seconds,4), "network_requests":request_count, "body_bytes":body_bytes,
               "traffic_mb":round(body_bytes/1_000_000,6), "peak_memory_mb":round(memory.peak/1_000_000,3),
               "stop_reason":reason, "started_at":run, "finished_at":now()}
    return table, metrics


def collect_all(folder, method):
    """Общий набор: основной каталог и первые 60 ноутбуков."""
    import webscraper_source
    started = time.perf_counter()
    if method == "browser":
        first, a, _ = collect_browser(folder, max_records=240, extraction_test=True, method="browser_main")
        second, b = webscraper_source.collect_browser(folder, limit=60)
    else:
        first, a = collect_light(folder, max_records=240, method="light_main")
        second, b = webscraper_source.collect_light(folder, limit=60)
    table = pd.concat([first, second], ignore_index=True).sort_values("product_id").reset_index(drop=True)
    if table.duplicated("product_id").any() or table.duplicated("product_url").any():
        raise ValueError("Совпали ключи товаров разных источников")
    metrics = {
        "method":method, "records":len(table), "raw_cards":a["raw_cards"]+b["raw_cards"],
        "removed_duplicates":a["removed_duplicates"]+b["removed_duplicates"],
        "excluded_by_limit":a.get("excluded_by_limit",0)+b.get("excluded_by_limit",0),
        "seconds":round(time.perf_counter()-started,4),
        "network_requests":a["network_requests"]+b["network_requests"],
        "body_bytes":a["body_bytes"]+b["body_bytes"],
        "traffic_mb":round((a["body_bytes"]+b["body_bytes"])/1_000_000,6),
        "peak_memory_mb":max(a["peak_memory_mb"],b["peak_memory_mb"]),
        "clicks":a.get("clicks",0)+b.get("clicks",0),
        "timeouts":a.get("timeouts",0)+b.get("timeouts",0),
        "stop_reason":"sources_finished", "started_at":a["started_at"], "finished_at":now(),
        "source_counts":{"scrapingcourse":len(first),"webscraper":len(second)},
        "sources":{"scrapingcourse":a,"webscraper":b}, "extraction":a.get("extraction",{}),
    }
    return table, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["browser", "light", "benchmark"])
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    folder = Path(args.output)
    if args.mode == "browser":
        table, metrics = collect_all(folder, "browser")
        table.to_csv(folder/"data_browser.csv", index=False, encoding="utf-8-sig")
        save_json(folder/"browser_metrics.json", metrics)
        save_json(folder/"quality_browser.json", smoke_check(table))
        if metrics["timeouts"]:
            raise RuntimeError("При сборе были таймауты: частичный результат и артефакты сохранены")
    elif args.mode == "light":
        table, metrics = collect_all(folder, "light")
        table.to_csv(folder/"data_light.csv", index=False, encoding="utf-8-sig")
        save_json(folder/"light_metrics.json", metrics)
        save_json(folder/"quality_light.json", smoke_check(table))
        if (folder/"data_browser.csv").exists():
            browser = pd.read_csv(folder/"data_browser.csv")
            pd.testing.assert_frame_equal(browser, table, check_dtype=False)
            save_json(folder/"comparison_differences.json", {"same_results":True,"records":len(table),"differences":[]})
    else:
        samples = {"baseline":[], "browser":[], "light":[]}
        for repeat in range(3):
            baseline, a, _ = collect_browser(folder, max_clicks=1, block_resources=False, method="benchmark_baseline")
            optimized, b, _ = collect_browser(folder, max_clicks=1, method="benchmark_browser")
            light, c = collect_light(folder, max_clicks=1, method="benchmark_light")
            pd.testing.assert_frame_equal(baseline, optimized)
            pd.testing.assert_frame_equal(optimized, light)
            for key, value in [("baseline",a),("browser",b),("light",c)]:
                samples[key].append(value)
        def aggregate(values):
            result = dict(values[0])
            for key in ["seconds","network_requests","traffic_mb","body_bytes"]:
                result[key] = statistics.median(row[key] for row in values)
            result["peak_memory_mb"] = max(row["peak_memory_mb"] for row in values)
            return result
        a,b,c = [aggregate(samples[key]) for key in ["baseline","browser","light"]]
        save_json(folder/"benchmark_metrics.json", {"baseline":a,"browser":b,"light":c,"samples":samples,"repeats":3,
                  "time_saved_percent":100*(a["seconds"]-b["seconds"])/a["seconds"],
                  "traffic_saved_percent":100*(a["traffic_mb"]-b["traffic_mb"])/a["traffic_mb"]})
        metrics = {"benchmark_records":len(optimized),"baseline_seconds":a["seconds"],"blocked_seconds":b["seconds"],"light_seconds":c["seconds"]}
    print(json.dumps(metrics,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
