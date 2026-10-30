"""A local web app for automation tests; no user accounts or external services."""

import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PAGE = """<!doctype html><meta charset="utf-8"><title>Workspace browser fixture</title>
<label>Name <input id="name"></label>
<label>Password <input type="password" value="fixture-private-password"></label>
<label>Code <input autocomplete="one-time-code" value="fixture-private-code"></label>
<label>Choice <select id="choice"><option value="alpha">Alpha</option><option value="beta">Beta</option></select></label>
<label>Enabled <input type="checkbox" id="enabled"></label>
<button id="save">Save</button><output id="result">Waiting</output><div id="shadow"></div>
<div style="height:900px">Scroll past this space</div><iframe name="embedded" src="/frame"></iframe>
<script>
document.querySelector('#save').onclick = () => {
    const value = document.querySelector('#name').value + ':' + document.querySelector('#choice').value
        + ':' + document.querySelector('#enabled').checked;
    document.querySelector('#result').textContent = value;
    localStorage.setItem('saved', value);
};
const shadow = document.querySelector('#shadow').attachShadow({mode:'open'});
const button = document.createElement('button');
button.textContent = 'Shadow action';
button.onclick = () => document.title = 'Shadow clicked';
shadow.append(button);
</script>"""

FRAME = """<!doctype html><title>Frame</title>
<button id="frame" onclick="document.querySelector('output').textContent = 'Frame clicked'">Frame action</button>
<output>Frame waiting</output>"""


@dataclass(frozen=True, slots=True)
class Attachment:
    content: bytes
    content_type: str
    cookie: str


@contextmanager
def fixture(page: str = PAGE, *, pages: Mapping[str, str | Attachment] | None = None) -> Generator[str]:
    # Snapshot the scenario documents before the server thread starts; requests
    # never observe changes to module globals or a caller's route catalog.
    routes = frozendict(pages or {})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            match routes.get(path, FRAME if path == "/frame" else page):
                case Attachment(content=data, content_type=content_type, cookie=cookie):
                    status = 200 if cookie in self.headers.get("Cookie", "") else 401
                case str() as text:
                    data, content_type, status = text.encode("utf-8"), "text/html; charset=utf-8", 200
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "require-trusted-types-for 'script'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
