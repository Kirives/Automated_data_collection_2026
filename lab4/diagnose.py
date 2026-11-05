"""Диагностика источника и учебная проверка сохранения артефактов таймаута."""
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from collect import URL, AJAX, USER_AGENT, CARD, browser_options, save_failure, save_json


def main():
    folder = Path(__file__).resolve().parent
    artifacts = folder / "artifacts"
    artifacts.mkdir(exist_ok=True)
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        robots = session.get("https://www.scrapingcourse.com/robots.txt", timeout=25)
        robots.raise_for_status()
        robot_parser = RobotFileParser()
        robot_parser.parse(robots.text.splitlines())
        if not all(robot_parser.can_fetch(USER_AGENT, url) for url in [URL, AJAX]):
            raise RuntimeError("robots.txt не разрешает выбранный путь")
        (artifacts/"robots.txt").write_text(robots.text,encoding="utf-8")
        response = session.get(URL, timeout=25)
        response.raise_for_status()
    initial = response.text
    (artifacts/"initial.html").write_text(initial,encoding="utf-8")
    soup = BeautifulSoup(initial,"html.parser")
    result = {"requests_html_bytes":len(response.content),"requests_cards":len(soup.select(".product-item")),
              "first_product_in_html":soup.select_one(".product-name").get_text() in initial,
              "first_product_location":"HTML product card", "inline_json_dataset":False,
              "robots_source_allowed":True,"robots_ajax_allowed":True}
    with sync_playwright() as p:
        browser = p.chromium.launch(**browser_options())
        try:
            for enabled in [True,False]:
                context = browser.new_context(user_agent=USER_AGENT,viewport={"width":1280,"height":900},locale="en-US",java_script_enabled=enabled)
                context.set_default_timeout(15000)
                context.set_default_navigation_timeout(30000)
                try:
                    page = context.new_page()
                    page.route("**/*",lambda route: route.abort() if route.request.resource_type in {"image","font","media"} else route.continue_())
                    page.goto(URL,wait_until="domcontentloaded")
                    page.locator(CARD).first.wait_for()
                    before = page.locator(CARD).count()
                    if enabled:
                        with page.expect_response(lambda r:urlparse(r.url).path=="/ajax/products") as info:
                            page.get_by_test_id("load-more-btn").click()
                        fetched = info.value
                        page.wait_for_function("n => document.querySelectorAll('.product-item').length > n",arg=before)
                        target = page.locator(".product-name").last.inner_text()
                        result.update({"initial_cards":before,"after_one_click":page.locator(CARD).count(),
                                       "new_target_text":target,"target_in_initial_html":target in initial,
                                       "xhr":{"url":fetched.url,"method":fetched.request.method,"status":fetched.status,
                                              "content_type":fetched.headers.get("content-type"),"body_bytes":len(fetched.body())}})
                        page.screenshot(path=str(artifacts/"diagnostic_browser.png"),full_page=False)
                        try:
                            page.get_by_test_id("lab4-intentionally-missing").wait_for(timeout=500)
                        except PlaywrightTimeoutError as error:
                            save_failure(page,folder,"timeout_demo")
                            save_json(artifacts/"timeout_demo.json",{"expected_timeout":True,"message":str(error),
                                      "continued_records":page.locator(CARD).count(),"purpose":"Учебная проверка отсутствующего локатора; не сбой сайта"})
                    else:
                        page.get_by_test_id("load-more-btn").click()
                        result.update({"no_js_cards_before":before,"no_js_cards_after_click":page.locator(CARD).count()})
                        page.screenshot(path=str(artifacts/"diagnostic_no_js.png"),full_page=False)
                finally:
                    context.close()
        finally:
            browser.close()
    save_json(artifacts/"diagnosis.json",result)
    from webscraper_source import diagnose
    diagnose(folder)
    print("Диагностика завершена; ожидаемый таймаут сохранён, после него обработка продолжилась.")


if __name__ == "__main__":
    main()
