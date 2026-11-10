from unittest.mock import patch
import pytest
from backend.extractors.ytdlp_extractor import format_selector, normalize

FORMATS = [
    {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 30, "ext": "mp4"},
    {"format_id": "22", "vcodec": "avc1", "acodec": "aac", "height": 720, "fps": 30, "ext": "mp4"},
    {"format_id": "140", "vcodec": "none", "acodec": "aac", "ext": "m4a"},
]

def test_default():
    assert format_selector("best", FORMATS, True) == "bestvideo*+bestaudio/best"
    assert format_selector("best", FORMATS, False) == "best[vcodec!=none][acodec!=none]"

def test_video_audio_merge():
    assert format_selector("137", FORMATS, True) == "137+bestaudio/best"
    assert format_selector("22", FORMATS, False) == "22"

@pytest.mark.parametrize("fmt", ["137", "140", "missing"])
def test_no_ffmpeg_or_unavailable(fmt):
    with pytest.raises(ValueError): format_selector(fmt, FORMATS, False)

def test_drm_selection():
    with pytest.raises(ValueError): format_selector("d", [{"format_id": "d", "has_drm": True}], True)

def test_sort_and_single_file_filter():
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        item = normalize({"title": "Example", "formats": FORMATS}, "https://example.org/video")
        assert [f.height for f in item.formats] == [1080, 720]
        assert item.formats[0].note == "Best"
    with patch("shutil.which", return_value=None):
        assert [f.height for f in normalize({"formats": FORMATS}, "https://example.org/video").formats] == [720]

def test_all_protected():
    item = normalize({"formats": [{**f, "has_drm": True} for f in FORMATS]}, "https://example.org/video")
    assert item.drm and not item.formats
