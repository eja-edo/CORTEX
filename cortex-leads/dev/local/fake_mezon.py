"""`python -m dev.local.fake_mezon [port] [file]`: a stand-in for a Mezon channel webhook (WP31). Every POST {"text": ...}
is appended to the file and shown at GET /, so one "account" collects all pushes while the real channel is not set up."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8301
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "data/fake_mezon.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(json.loads(body), ensure_ascii=False) + "\n")
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        posts = [json.loads(line)["text"] for line in OUT.read_text(encoding="utf-8").splitlines()] if OUT.exists() else []
        page = "<meta charset=utf-8><title>Mezon giả</title><body style='font:15px sans-serif;max-width:640px;margin:2em auto'>" + "".join(
            f"<pre style='white-space:pre-wrap;background:#eef;padding:1em;border-radius:8px'>{p}</pre>" for p in posts)
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    print(f"Mezon giả: http://127.0.0.1:{PORT}  (ghi vào {OUT})", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
