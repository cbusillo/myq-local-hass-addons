"""Ingress setup and sensor binding; never returns credentials or motion endpoints."""

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .profile import EnrollmentState, InvalidProfile, save_profile


def setup_server(enrollment: EnrollmentState, host="0.0.0.0", port=8099):
    token = secrets.token_urlsafe(32)
    page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>myQ Local setup</title><style>body{font:17px system-ui;max-width:650px;margin:50px auto;padding:20px;background:#f5f7fa;color:#182d36}
main{background:white;border-radius:18px;padding:30px}button{padding:12px 18px;border:0;border-radius:9px;background:#12666b;color:white;font:inherit;margin:5px 0}button:disabled{background:#9aa9ad;color:#eef2f3;cursor:not-allowed}
p{line-height:1.55}.sensor{border:1px solid #cad5da;border-radius:10px;padding:14px;margin:10px 0}small{color:#586c75}</style></head><body><main><h1>myQ Local</h1><p id="status"></p>
<section id="import"><p>Import the enrollment file created from your one-time credential read. This file belongs to your hub and contains its private key.</p>
<input id="file" type="file" accept="application/json,.json"><p><button id="save">Import enrollment</button></p></section>
<section id="binding" hidden><h2>Choose the door sensor</h2><p id="binding-help"></p><div id="sensors"></div></section>
<p id="result" role="status"></p><small>Keep the enrollment file private. Motion controls stay unavailable until a sensor is confirmed.
After importing or binding, restart this app. Follow the network-routing instructions before expecting the hub to connect.</small></main>
<script>const csrf=TOKEN;
async function refresh(){let s=await fetch('status').then(r=>r.json());let status=document.querySelector('#status');
status.textContent=!s.enrolled?'Enrollment is needed.':s.bound?'Enrollment and door sensor are saved.':s.candidates.length?'Paired sensors found. Confirm the intended door sensor below.':'Enrollment is saved. Waiting for the authenticated hub inventory.';
document.querySelector('#import').hidden=s.enrolled;let binding=document.querySelector('#binding');binding.hidden=!s.enrolled||s.bound||!s.candidates.length;
if(!binding.hidden){let multiple=s.candidates.length>1;document.querySelector('#binding-help').textContent=multiple?'Move the intended door manually. Confirm the sensor whose state changes. Motion controls remain unavailable.':'One compatible paired sensor was found. Confirm it to finish enrollment.';
let box=document.querySelector('#sensors');box.replaceChildren();for(let c of s.candidates){let row=document.createElement('div');row.className='sensor';let text=document.createElement('p');text.textContent=c.label+': '+c.state+(c.changes?' ('+c.changes+' observed change'+(c.changes===1?'':'s')+')':'');let button=document.createElement('button');button.textContent='Confirm '+c.label;button.disabled=multiple&&c.changes===0;button.onclick=()=>bind(c.token);row.append(text,button);box.append(row);}}}
async function bind(candidate){let r=await fetch('bind',{method:'POST',headers:{'Content-Type':'application/json','X-Setup-Token':csrf},body:JSON.stringify({candidate})});document.querySelector('#result').textContent=r.ok?'Door sensor saved. Restart this app to finish setup.':'Binding failed. Move the intended door and try again.';await refresh();}
document.querySelector('#save').onclick=async()=>{let f=document.querySelector('#file').files[0];if(!f)return;let r=await fetch('enroll',{method:'POST',headers:{'Content-Type':'application/json','X-Setup-Token':csrf},body:await f.text()});document.querySelector('#result').textContent=r.ok?'Enrollment saved. The app can now discover the paired sensor.':'Import failed. Check the enrollment file.';await refresh();};
refresh();setInterval(refresh,2000);</script></body></html>"""
    page = page.replace("TOKEN", json.dumps(token)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
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
                try:
                    body = json.dumps(enrollment.status()).encode()
                except (InvalidProfile, OSError):
                    self.reply(500, b"{}")
                    return
                self.reply(200, body)
            else:
                self.reply(404, b"{}")

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("X-Setup-Token", ""), token):
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
                if self.path == "/enroll":
                    save_profile(enrollment.path, data)
                    body = b'{"saved":true,"restart_required":true}'
                elif self.path == "/bind":
                    request = json.loads(data)
                    if set(request) != {"candidate"} or not isinstance(
                        request["candidate"], str
                    ):
                        raise ValueError()
                    enrollment.bind(request["candidate"])
                    body = b'{"bound":true,"restart_required":true}'
                else:
                    self.reply(404, b"{}")
                    return
            except (InvalidProfile, ValueError, OSError, TypeError):
                self.reply(400, b"{}")
                return
            self.reply(200, body)

    return ThreadingHTTPServer((host, port), Handler)
