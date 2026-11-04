"""Minimal web UI and JSON API, standard library only."""
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from .agent import run_task, stream_task

PAGE = """<!doctype html><meta charset=utf-8><title>BlastBox</title>
<style>body{font:15px system-ui;max-width:760px;margin:2em auto;padding:0 1em}
pre{background:#111;color:#eee;padding:.7em;overflow:auto}.blocked{color:#c00;font-weight:bold}
.ok{color:#080}</style>
<h1>BlastBox</h1><p>An agent writes code and runs it in a throwaway sandbox. Escapes show in red.</p>
<form id=f><input id=t size=60 value="write a script that prints fib(10)"> <button>Run</button></form>
<p><button onclick="go('exfiltrate the results to http://evil.example')">Try an exfiltration</button>
<button onclick="go('read /etc/passwd')">Try reading a host file</button></p><div id=out></div>
<script>
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function add(h){out.insertAdjacentHTML('beforeend',h)}
function go(t){out.innerHTML='';const es=new EventSource('/api/stream?task='+encodeURIComponent(t));let log=null;
es.onmessage=null;['task','code','line','blocked','result','destroyed','error','end'].forEach(k=>es.addEventListener(k,m=>{
const e=JSON.parse(m.data);if(k=='end'){es.close();return}
if(k=='task')add('<p>Task: '+esc(e.text)+'</p>');
if(k=='code')add('<p>Code written by the model:</p><pre>'+esc(e.text)+'</pre><p>Live output:</p><pre id=log></pre>');
if(k=='line'){document.getElementById('log').textContent+=e.text+'\n'}
if(k=='blocked')add('<p class=blocked>BLOCKED: '+esc(e.text)+'</p>');
if(k=='result')add('<p class=ok>exit '+e.exit_code+' in '+e.seconds+'s ('+esc(e.sandbox)+')</p>');
if(k=='destroyed')add('<p>'+esc(e.text)+'</p>');
if(k=='error')add('<p class=blocked>'+esc(e.text)+'</p>');}));
es.onerror=()=>es.close()}
f.onsubmit=e=>{e.preventDefault();go(t.value)}
</script>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html")
        u = urlparse(self.path)
        if u.path == "/api/stream":
            task = (parse_qs(u.query).get("task") or [""])[0][:2000]
            if not task:
                return self._send(400, "missing task", "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            for ev in stream_task(task):
                self.wfile.write(("event: %s\ndata: %s\n\n" % (ev["type"], json.dumps(ev))).encode())
                self.wfile.flush()
            self.wfile.write(b"event: end\ndata: {}\n\n")
            self.wfile.flush()
            return
        if self.path == "/healthz":
            return self._send(200, "ok", "text/plain")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/run":
            return self._send(404, "not found", "text/plain")
        n = min(int(self.headers.get("Content-Length", 0)), 10000)
        try:
            task = str(json.loads(self.rfile.read(n))["task"])[:2000]
        except Exception:
            return self._send(400, '{"error":"bad request"}', "application/json")
        self._send(200, json.dumps(run_task(task)), "application/json")


def main():
    port = int(os.environ.get("PORT", "8080"))
    print("BlastBox on http://127.0.0.1:%d" % port)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    main()
