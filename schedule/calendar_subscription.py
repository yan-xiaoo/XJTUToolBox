"""Opt-in LAN delivery of an already serialized calendar, using the stdlib."""
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _CalendarHTTPServer(ThreadingHTTPServer):
    # SO_REUSEADDR permits duplicate listeners on Windows, hiding port conflicts.
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False
    request_deadline = 5

    def __init__(self, *args, **kwargs):
        self._requests = set()
        self._request_lock = threading.Lock()
        self._closing = False
        super().__init__(*args, **kwargs)

    @staticmethod
    def _interrupt(request):
        try:
            request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def process_request(self, request, client_address):
        with self._request_lock:
            accepted = not self._closing and len(self._requests) < 8
            if accepted:
                self._requests.add(request)
        if not accepted:
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            with self._request_lock:
                self._requests.discard(request)
            raise

    def process_request_thread(self, request, client_address):
        # An inactivity timeout alone does not bound a drip-fed request.
        timer = threading.Timer(self.request_deadline, self._interrupt, (request,))
        timer.daemon = True
        timer.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            with self._request_lock:
                self._requests.discard(request)

    def handle_error(self, request, client_address):
        pass  # Interrupted clients must not log request paths or tokens.

    def interrupt_requests(self):
        with self._request_lock:
            self._closing = True
            for request in self._requests:
                self._interrupt(request)


def is_lan_address(value):
    try:
        address = ipaddress.ip_address(value)
        return any(address in ipaddress.ip_network(net) for net in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))
    except ValueError:
        return False


def load_token(directory):
    path = Path(directory) / "calendar-subscription-token"
    try:
        token = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        token = secrets.token_urlsafe(32)
        # A stable per-account URL, without storing any school/GitHub credential.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return load_token(directory)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(token)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("本地订阅标识损坏，请移除 calendar-subscription-token 文件后重新开启订阅")
    return token


class CalendarSubscription:
    def __init__(self):
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._data = None
        self._etag = None
        self.url = None

    @property
    def running(self):
        return self._server is not None

    def update(self, data):
        if not isinstance(data, bytes) or not data.startswith(b"BEGIN:VCALENDAR"):
            raise ValueError("无效的日历数据")
        with self._lock:
            self._data = data
            self._etag = '"' + hashlib.sha256(data).hexdigest() + '"'

    def start(self, address, port, token, data):
        if self.running:
            raise RuntimeError("订阅已开启")
        if not is_lan_address(address):
            raise ValueError("请选择本机局域网 IPv4 地址")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("无效的订阅标识")
        self.update(data)
        path = f"/{token}/calendar.ics"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def log_message(self, *_args):
                pass  # Do not put the bearer URL in logs.

            def do_GET(self):
                self._calendar(False)

            def do_HEAD(self):
                self._calendar(True)

            def _calendar(self, head):
                if not hmac.compare_digest(self.path.encode(), path.encode()):
                    self.send_error(404)
                    return
                with owner._lock:
                    payload, etag = owner._data, owner._etag
                if payload is None:
                    self.send_error(503)
                    return
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "private, no-cache")
                self.send_header("ETag", etag)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not head:
                    try:
                        self.wfile.write(payload)
                    except (OSError, TimeoutError):
                        pass

        server = _CalendarHTTPServer((address, port), Handler)
        self._server = server
        self.url = f"http://{address}:{server.server_port}{path}"
        self._thread = threading.Thread(target=server.serve_forever,
                                        kwargs={"poll_interval": 0.1}, daemon=True)
        try:
            self._thread.start()
        except Exception:
            server.server_close()
            self._server = self._thread = self.url = None
            raise
        return self.url

    def stop(self):
        with self._lock:
            self._data = self._etag = None
        if self._server is not None:
            self._server.interrupt_requests()
            # Only wait for the listener's short poll, never for a client.
            self._server.shutdown()
            self._server.server_close()
            self._thread.join()
        self._server = self._thread = self.url = None
