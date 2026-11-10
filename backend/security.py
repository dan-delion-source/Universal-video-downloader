"""URL checks and a DNS-pinning proxy shared by every network consumer.

The proxy connects to the exact public address it checked. Each redirect and
CONNECT opens a fresh checked connection, avoiding check-then-resolve races.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import re
import select
import socket
import threading
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .config import NETWORK_TIMEOUT


class UnsafeURL(ValueError):
    pass


def parse_url(url: str):
    if any(ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise UnsafeURL("URL contains invalid characters.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("Invalid URL or port.") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL("Enter a full http:// or https:// URL.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("URLs containing credentials are not supported.")
    if port is not None and port not in (80, 443):
        raise UnsafeURL("Only standard web ports (80 and 443) are supported.")
    return parts


def public_addresses(host: str, port: int) -> list[tuple]:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL("Could not resolve this hostname.") from exc
    if not addresses:
        raise UnsafeURL("Hostname has no addresses.")
    for _, _, _, _, addr in addresses:
        ip = ipaddress.ip_address(addr[0].split("%")[0])
        translated = ip.version == 6 and any(ip in ipaddress.ip_network(prefix) for prefix in
            ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or translated or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise UnsafeURL("Private, local, and reserved network addresses are blocked.")
    return addresses


def validate_url(url: str) -> str:
    parts = parse_url(url)
    public_addresses(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def sanitize_filename(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f%]', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)[:110].rstrip(" .") or "video"
    value = value.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .") or "video"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


def safe_file(directory: Path, name: str) -> Path:
    if not name or name != Path(name).name or "/" in name or "\\" in name or name.startswith("."):
        raise UnsafeURL("Invalid filename.")
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise UnsafeURL("Invalid file path.")
    return path


def _connect(host: str, port: int):
    for family, kind, proto, _, addr in public_addresses(host, port):
        conn = socket.socket(family, kind, proto)
        conn.settimeout(NETWORK_TIMEOUT)
        try:
            conn.connect(addr)
            return conn
        except OSError:
            conn.close()
    raise UnsafeURL("Could not connect to the remote server.")


class GuardProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = NETWORK_TIMEOUT

    def log_message(self, *_):
        pass  # Requests can contain signed URLs or cookies.

    def relay(self, upstream):
        peers = [self.connection, upstream]
        while True:
            ready, _, _ = select.select(peers, [], [], NETWORK_TIMEOUT * 2)
            if not ready:
                return
            for peer in ready:
                data = peer.recv(65536)
                if not data:
                    return
                (upstream if peer is self.connection else self.connection).sendall(data)

    def do_CONNECT(self):
        try:
            parts = parse_url("https://" + self.path)
            if (parts.port or 443) != 443:
                raise UnsafeURL("TLS requires port 443.")
            with _connect(parts.hostname, 443) as upstream:
                self.send_response(200)
                self.end_headers()
                self.relay(upstream)
        except (OSError, ValueError):
            self.close_connection = True

    def do_GET(self):
        try:
            parts = parse_url(self.path)
            if parts.scheme != "http":
                raise UnsafeURL("HTTPS requires CONNECT.")
            with _connect(parts.hostname, parts.port or 80) as upstream:
                target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
                headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "proxy-connection", "proxy-authorization", "connection"}}
                headers.update({"Host": parts.netloc, "Connection": "close"})
                head = f"{self.command} {target} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
                upstream.sendall(head.encode("latin-1"))
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                    raise UnsafeURL("Unsupported request body.")
                if length:
                    upstream.sendall(self.rfile.read(length))
                self.relay(upstream)
        except (OSError, ValueError):
            self.close_connection = True

    do_HEAD = do_GET
    do_POST = do_GET


@contextmanager
def guarded_proxy():
    server = ThreadingHTTPServer(("127.0.0.1", 0), GuardProxy)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
