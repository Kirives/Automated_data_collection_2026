"""Локальный API рендеринга для HTTP Request в n8n. Только учебный источник."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from collect import URL, collect_browser, save_json

FOLDER = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status":"ok"})
        else:
            self.send_json(404, {"error":"Not found"})

    def do_POST(self):
        if self.path != "/render":
            self.send_json(404, {"error":"Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                raise ValueError("Ожидался небольшой JSON-запрос")
            body = json.loads(self.rfile.read(length))
            if body.get("url") != URL or body.get("javascript") is not True:
                raise ValueError("Разрешена только учебная страница с включённым JavaScript")
            if body.get("wait_selector") != ".product-item":
                raise ValueError("Нужно ожидание .product-item")
            clicks = int(body.get("clicks", 1))
            if clicks < 1 or clicks > 3:
                raise ValueError("Допустимо от 1 до 3 кликов")
        except (ValueError, TypeError) as error:
            self.send_json(400, {"error":str(error)})
            return
        try:
            _, metrics, html = collect_browser(FOLDER, max_clicks=clicks, keep_html=True, method="n8n_renderer")
            if metrics.get("timeouts",0):
                raise RuntimeError("Рендеринг завершился с таймаутом; артефакты сохранены")
            metrics["render_requests"] = 1
            save_json(FOLDER/"nocode"/"render_metrics.json", metrics)
            self.send_json(200, {"html":html,"metrics":metrics})
        except Exception as error:
            # Ошибка возвращается HTTP-клиенту и направляется в ветку ошибок n8n.
            print(f"Ошибка рендеринга: {type(error).__name__}: {error}", flush=True)
            self.send_json(500, {"error":f"{type(error).__name__}: {error}"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host,args.port),Handler)
    print(f"API рендеринга: http://{args.host}:{args.port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("API остановлен",flush=True)
    finally:
        server.server_close()
