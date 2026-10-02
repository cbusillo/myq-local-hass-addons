"""Ingress setup page; never returns enrollment contents or motion endpoints."""

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .profile import InvalidProfile, save_profile


def setup_server(path: Path, host="0.0.0.0", port=8099):
    token = secrets.token_urlsafe(32)
    page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>myQ Local setup</title><style>body{font:17px system-ui;max-width:650px;margin:50px auto;padding:20px;background:#f5f7fa;color:#182d36}
main{background:white;border-radius:18px;padding:30px}button{padding:12px 18px;border:0;border-radius:9px;background:#12666b;color:white;font:inherit}
p{line-height:1.55}small{color:#586c75}</style></head><body><main><h1>myQ Local</h1><p id="status"></p>
<p>Import the enrollment file created from your one-time credential read. This file belongs to your hub and contains its private key.</p>
<input id="file" type="file" accept="application/json,.json"><p><button id="save">Import enrollment</button></p>
<p id="result" role="status"></p><small>Keep the file private. Home Assistant controls remain disabled until you enable them in this app's configuration.
After importing, restart this app. Follow the network-routing instructions before expecting the hub to connect.</small></main>
<script>const csrf=TOKEN;
fetch('status').then(r=>r.json()).then(s=>document.querySelector('#status').textContent=s.enrolled?'Enrollment is saved.':'Enrollment is needed.');
document.querySelector('#save').onclick=async()=>{let f=document.querySelector('#file').files[0];if(!f)return;
let r=await fetch('enroll',{method:'POST',headers:{'Content-Type':'application/json','X-Setup-Token':csrf},body:await f.text()});
document.querySelector('#result').textContent=r.ok?'Enrollment saved. Restart this app to use it.':'Import failed. Check the enrollment file.';};</script></body></html>"""
    page = page.replace("TOKEN", json.dumps(token)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, kind="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.reply(200, page, "text/html; charset=utf-8")
            elif self.path == "/status":
                self.reply(200, json.dumps({"enrolled": path.exists()}).encode())
            else:
                self.reply(404, b"{}")

        def do_POST(self):
            if self.path != "/enroll" or not hmac.compare_digest(
                self.headers.get("X-Setup-Token", ""), token
            ):
                self.reply(403, b"{}")
                return
            if self.headers.get("Content-Type") != "application/json":
                self.reply(415, b"{}")
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= 4096:
                    raise ValueError()
                self.connection.settimeout(5)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError()
                save_profile(path, data)
            except (InvalidProfile, ValueError, OSError):
                self.reply(400, b"{}")
                return
            self.reply(200, b'{"saved":true,"restart_required":true}')

    return ThreadingHTTPServer((host, port), Handler)
