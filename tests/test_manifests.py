import pytest
from backend.manifests import inspect_manifests, playlist_children, ProtectedStream
from backend.models import DownloadRequest


def test_extensionless_children():
    text = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,URI="audio?lang=en",GROUP-ID="a"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1000,URI="iframes?id=1"
#EXT-X-STREAM-INF:BANDWIDTH=3000000
variant?id=1080
'''
    assert playlist_children(text, "https://cdn.example.org/live/master") == [
        "https://cdn.example.org/live/audio?lang=en", "https://cdn.example.org/live/iframes?id=1",
        "https://cdn.example.org/live/variant?id=1080"]


def test_extensionless_encryption_rejected_before_download():
    seen = []
    def fetch(url, proxy):
        seen.append(url)
        text = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3000\nvariant?id=1' if url.endswith("master") else '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\nsegment.ts'
        return text, url, "application/vnd.apple.mpegurl"
    with pytest.raises(ProtectedStream): inspect_manifests(["https://cdn.example.org/master"], "proxy", fetch=fetch)
    assert seen == ["https://cdn.example.org/master", "https://cdn.example.org/variant?id=1"]


def test_redirect_base_and_cycle_are_handled():
    seen = []
    def fetch(url, proxy):
        seen.append(url)
        if len(seen) == 1:
            return '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nchild', "https://other.example.org/path/master", "text/plain"
        return '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nchild', url, "text/plain"
    inspect_manifests(["https://cdn.example.org/master"], "proxy", fetch=fetch)
    assert len(seen) == 2 and seen[1] == "https://other.example.org/path/child"


def test_manifest_depth_is_bounded():
    def fetch(url, proxy): return '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n' + url + '/next', url, "text/plain"
    with pytest.raises(ValueError, match="safe inspection limit"):
        inspect_manifests(["https://cdn.example.org/master"], "proxy", fetch=fetch)


def test_media_segments_are_not_fetched_as_playlists():
    text = '#EXTM3U\n#EXTINF:5,\nsegment.ts\n#EXTINF:5,\nsegment2.ts'
    assert playlist_children(text, "https://cdn.example.org/master") == []


def test_scanned_title_length_is_accepted_by_download():
    assert len(DownloadRequest(url="https://example.org/video", title="a" * 300).title) == 300
