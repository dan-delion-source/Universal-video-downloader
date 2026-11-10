import socket
from unittest.mock import patch
import pytest
from backend.security import UnsafeURL, validate_url, sanitize_filename, safe_file, _connect


def dns(address):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/v", "javascript:alert(1)", "http://user:password@example.com", "http://example.com:8080", "https://", "http://example.com/\r\nHost:evil", "http://example.com\\@localhost", "http://example.com:bad"])
def test_invalid_url(url):
    with pytest.raises(UnsafeURL): validate_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "192.0.2.1", "64:ff9b::7f00:1", "2002:7f00:1::", "2001::1"])
def test_ssrf(address):
    with patch("socket.getaddrinfo", return_value=dns(address)), pytest.raises(UnsafeURL):
        validate_url("https://example.com/video")


def test_public():
    with patch("socket.getaddrinfo", return_value=dns("93.184.216.34")):
        assert validate_url("https://example.com#fragment") == "https://example.com/"


def test_mixed_dns_rejected():
    with patch("socket.getaddrinfo", return_value=dns("93.184.216.34") + dns("127.0.0.1")), pytest.raises(UnsafeURL):
        validate_url("https://example.com")


def test_dns_failure():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror()), pytest.raises(UnsafeURL):
        validate_url("https://example.com")


def test_connect_pins_checked_address():
    with patch("socket.getaddrinfo", return_value=dns("93.184.216.34")) as resolve, patch("socket.socket") as create:
        _connect("example.com", 443)
        create.return_value.connect.assert_called_once_with(("93.184.216.34", 443))
        resolve.assert_called_once()


@pytest.mark.parametrize("value", ["../../etc/passwd", "bad\\name:*.mp4", "CON", "nul.txt", "\x00video", " . ", "%(id)s", "a" * 300])
def test_sanitizing(value):
    name = sanitize_filename(value)
    assert name and len(name) <= 111
    assert not any(c in name for c in '/\\:*?<>|%\x00')
    assert name.split('.')[0].upper() not in {"CON", "NUL"}


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "..", ".job-hidden", "video\\secret"])
def test_path_escape(tmp_path, name):
    with pytest.raises(UnsafeURL): safe_file(tmp_path, name)


def test_symlink_escape(tmp_path):
    (tmp_path / "link.mp4").symlink_to("/etc/passwd")
    with pytest.raises(UnsafeURL): safe_file(tmp_path, "link.mp4")


def test_safe_file(tmp_path):
    assert safe_file(tmp_path, "My video (1).mp4") == tmp_path / "My video (1).mp4"
