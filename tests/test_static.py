from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from backend.extractors.static_extractor import parse_html, protected_manifest, fetch_document


def test_html_fixture():
    items = parse_html((Path(__file__).parent / "fixtures/videos.html").read_text(), "https://example.org/watch/page")
    targets = {x.download_target for x in items}
    assert len(items) == 6
    assert "https://example.org/clips/a.mp4" in targets
    assert "https://example.org/stream/master.m3u8?token=123&x=2" in targets
    assert "https://cdn.example.org/dynamic.mpd?key=abc" in targets
    assert all(x.source == "static" and x.thumbnail == "https://example.org/poster.jpg" for x in items)
    assert next(x for x in items if x.download_target.endswith("film.mp4")).title == "A film"


def test_empty_and_malformed_json():
    assert parse_html('<script type="application/ld+json">broken</script>', "https://example.org/") == []


@pytest.mark.parametrize("text", ['#EXT-X-KEY:METHOD=AES-128,URI="key"', '#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="skd://key"', '<ContentProtection schemeIdUri="widevine"/>', '<cenc:ContentProtection/>', 'PlayReady', 'FairPlay'])
def test_protected(text): assert protected_manifest(text)


@pytest.mark.parametrize("text", ['#EXTM3U\n#EXT-X-KEY:METHOD=NONE\nsegment.ts', '<MPD><Period /></MPD>'])
def test_clear(text): assert not protected_manifest(text)


def test_redirect_revalidated():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}))
    original = httpx.Client
    with patch("backend.extractors.static_extractor.httpx.Client", side_effect=lambda **kw: original(transport=transport)), patch("backend.extractors.static_extractor.validate_url") as validate:
        validate.side_effect = ["https://example.org", ValueError("Private address")]
        with pytest.raises(ValueError, match="Private"): fetch_document("https://example.org", "http://unused")
        assert validate.call_args.args[0] == "http://127.0.0.1/secret"
