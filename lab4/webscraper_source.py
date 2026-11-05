"""Учебный каталог ноутбуков: кнопка More и JSON в исходном HTML."""
import json
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from collect import (USER_AGENT, PeakMemory, append_log, browser_options, normalize,
                     now, save_failure, save_json)

URL = "https://webscraper.io/test-sites/e-commerce/more/computers/laptops"
PRODUCT_BASE = "https://webscraper.io/test-sites/e-commerce/more/product/"
CARD = ".ecomerce-items [itemtype='https://schema.org/Product']"
MORE = "a.ecomerce-items-scroll-more"
EXTRACT = """cards => cards.map(card => ({
    name: card.querySelector('a[itemprop="name"]')?.getAttribute('title')
          || card.querySelector('a[itemprop="name"]')?.textContent || '',
    price: card.querySelector('[itemprop="offers"]')?.textContent || '',
    product_url: card.querySelector('a[itemprop="name"]')?.href || ''
}))"""


def get_page(session, url):
    """Таймаут и ограниченные повторы временных ошибок."""
    for attempt in range(3):
        response = session.get(url, timeout=(5, 30))
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
            return response
        if attempt == 2:
            response.raise_for_status()
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        import random
        header = response.headers.get("Retry-After", "0")
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = max(0, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
        time.sleep(max(retry_after, 2**attempt + random.uniform(0, 0.25)))
    raise RuntimeError("Не удалось получить страницу")


def parse_embedded(html, limit=60):
    tag = BeautifulSoup(html, "html.parser").select_one(".ecomerce-items[data-items]")
    if tag is None:
        raise ValueError("Не найден массив data-items")
    items = json.loads(tag["data-items"])
    records = [{"name": item["title"], "price": item["price"],
                "product_url": PRODUCT_BASE + str(item["id"])} for item in items[:limit]]
    return normalize(records), len(items)


def collect_browser(folder, limit=60, max_iterations=30, stagnant_limit=2, pause=0.7):
    folder = Path(folder)
    run, started = now(), time.perf_counter()
    counts = {"requests_started": 0, "blocked": 0, "body_bytes": 0}
    clicks, timeouts, stagnant = 0, 0, 0
    reason = "max_iterations"
    with PeakMemory() as memory, sync_playwright() as p:
        browser = p.chromium.launch(**browser_options())
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width":1280,"height":900}, locale="en-US")
        context.set_default_timeout(15000)
        context.set_default_navigation_timeout(30000)
        try:
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.send("Network.setCacheDisabled", {"cacheDisabled":True})
            def request_event(event): counts["requests_started"] += 1
            def data_event(event): counts["body_bytes"] += event["dataLength"]
            cdp.on("Network.requestWillBeSent", request_event)
            cdp.on("Network.dataReceived", data_event)
            def route_request(route):
                if route.request.resource_type in {"image","font","media"}:
                    counts["blocked"] += 1
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", route_request)
            page.add_locator_handler(page.get_by_role("button", name="Decline", exact=True), lambda locator: locator.click())
            response = page.goto(URL, wait_until="domcontentloaded")
            page.locator(CARD).first.wait_for(state="visible")
            raw = page.locator(CARD).evaluate_all(EXTRACT)
            table = normalize(raw)
            append_log(folder, run=run, method="browser_webscraper", iteration=0, items=len(raw),
                       unique_items=len(table), growth=len(table), seconds=time.perf_counter()-started,
                       timestamp=now(), url=URL, status=response.status)
            for iteration in range(1, max_iterations + 1):
                if len(table) >= limit:
                    reason = "max_records"
                    break
                button = page.locator(MORE)
                if not button.is_visible():
                    reason = "button_hidden"
                    break
                before, tick = len(raw), time.perf_counter()
                time.sleep(pause)  # Пауза вежливости; готовность проверяется по DOM.
                try:
                    button.click()
                    clicks += 1
                    page.wait_for_function("n => document.querySelectorAll('.ecomerce-items [itemtype=\"https://schema.org/Product\"]').length > n", arg=before)
                    raw = page.locator(CARD).evaluate_all(EXTRACT)
                    current = normalize(raw)
                    growth = len(current) - len(table)
                    table = current
                    stagnant = stagnant + 1 if growth == 0 else 0
                    append_log(folder, run=run, method="browser_webscraper", iteration=iteration,
                        items=len(raw), unique_items=len(table), growth=growth,
                        seconds=time.perf_counter()-tick, timestamp=now(), url=URL, status=200)
                except PlaywrightTimeoutError as error:
                    timeouts += 1
                    stagnant += 1
                    save_failure(page, folder, f"timeout_webscraper_{iteration}")
                    append_log(folder, run=run, method="browser_webscraper", iteration=iteration,
                        items=len(raw), unique_items=len(table), growth=0, seconds=time.perf_counter()-tick,
                        timestamp=now(), url=URL, error=str(error)[:250])
                if stagnant >= stagnant_limit:
                    reason = "no_growth"
                    break
            page.screenshot(path=str(folder/"artifacts/webscraper_browser.png"), full_page=False)
        except PlaywrightTimeoutError:
            save_failure(page, folder, "timeout_webscraper_page")
            raise
        finally:
            context.close()
            browser.close()
    table = table.head(limit)
    metrics = {"method":"browser_webscraper", "records":len(table), "raw_cards":len(raw),
        "removed_duplicates":len(raw)-len(normalize(raw)), "clicks":clicks, "timeouts":timeouts,
        "stop_reason":reason, "seconds":round(time.perf_counter()-started,4),
        "network_requests":counts["requests_started"]-counts["blocked"], **counts,
        "traffic_mb":round(counts["body_bytes"]/1_000_000,6), "peak_memory_mb":round(memory.peak/1_000_000,3),
        "started_at":run, "finished_at":now()}
    if len(table) < limit and not timeouts:
        raise RuntimeError(f"Получено только {len(table)} ноутбуков вместо {limit}")
    return table, metrics


def collect_light(folder, limit=60):
    folder = Path(folder)
    run, started = now(), time.perf_counter()
    with PeakMemory() as memory, requests.Session() as session:
        session.headers.update({"User-Agent":USER_AGENT,"Accept":"text/html","Accept-Encoding":"identity"})
        response = get_page(session, URL)
        table, available = parse_embedded(response.text, limit)
        append_log(folder, run=run, method="light_webscraper", iteration=0, items=available,
            unique_items=len(table), growth=len(table), seconds=time.perf_counter()-started,
            timestamp=now(), url=response.url, status=response.status_code)
    if len(table) < limit:
        raise RuntimeError(f"В JSON только {len(table)} ноутбуков вместо {limit}")
    return table, {"method":"light_webscraper","records":len(table),"raw_cards":available,
        "removed_duplicates":0,"excluded_by_limit":max(0,available-limit),"pages":1,"seconds":round(time.perf_counter()-started,4),
        "network_requests":1,"body_bytes":len(response.content),"traffic_mb":len(response.content)/1_000_000,
        "peak_memory_mb":round(memory.peak/1_000_000,3),"stop_reason":"max_records",
        "started_at":run,"finished_at":now()}


def diagnose(folder):
    folder = Path(folder)
    artifacts = folder/"artifacts"
    artifacts.mkdir(exist_ok=True)
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        robots = get_page(session,"https://webscraper.io/robots.txt")
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        if not parser.can_fetch(USER_AGENT, URL):
            raise RuntimeError("robots.txt не разрешает страницу каталога")
        response = get_page(session, URL)
    (artifacts/"webscraper_robots.txt").write_text(robots.text,encoding="utf-8")
    (artifacts/"webscraper_initial.html").write_text(response.text,encoding="utf-8")
    table, total = parse_embedded(response.text,117)
    with sync_playwright() as p:
        browser = p.chromium.launch(**browser_options())
        context = browser.new_context(java_script_enabled=False,user_agent=USER_AGENT,viewport={"width":1280,"height":900},locale="en-US")
        try:
            page = context.new_page()
            page.goto(URL,wait_until="domcontentloaded",timeout=30000)
            before = page.locator(CARD).count()
            page.locator(MORE).click(timeout=15000)
            after = page.locator(CARD).count()
            page.screenshot(path=str(artifacts/"webscraper_no_js.png"),full_page=False)
        finally:
            context.close()
            browser.close()
    result={"url":URL,"robots_allowed":True,"requests_html_bytes":len(response.content),
        "requests_cards":len(BeautifulSoup(response.text,"html.parser").select(CARD)),
        "inline_json":True,"inline_location":".ecomerce-items[data-items]", "available_items":total,
        "unique_items":len(table),"no_js_cards_before":before,"no_js_cards_after_click":after}
    save_json(artifacts/"webscraper_diagnosis.json",result)
    return result
