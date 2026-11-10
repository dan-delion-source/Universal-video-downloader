from typing import Literal
from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8192)


class MediaFormat(BaseModel):
    format_id: str
    resolution: str = "Original"
    fps: float | None = None
    ext: str = "mp4"
    filesize: int | None = None
    note: str = ""
    height: int = 0
    bitrate: float = 0
    video_only: bool = False


class MediaItem(BaseModel):
    id: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    source: Literal["yt-dlp", "static", "sniff"]
    drm: bool = False
    formats: list[MediaFormat] = Field(default_factory=list)
    download_target: str
    page_url: str | None = None


class DownloadRequest(ScanRequest):
    format_id: str = Field(default="best", min_length=1, max_length=200)
    title: str = Field(default="Video", max_length=300)
    browser_session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Job(BaseModel):
    id: str
    title: str
    status: Literal["queued", "downloading", "merging", "complete", "cancelled", "error"] = "queued"
    percent: float = 0
    speed: float | None = None
    eta: float | None = None
    filename: str | None = None
    error: str | None = None
    created_at: float


class BrowserCommand(BaseModel):
    action: Literal["navigate", "back", "reload", "click", "scroll", "type", "key", "stay", "activate", "close_tab", "follow_navigation", "dismiss_navigation"]
    url: str = Field(default="", max_length=8192)
    tab_id: str = Field(default="", max_length=32)
    navigation_id: str = Field(default="", max_length=32)
    x: float = Field(default=0, ge=0, le=959, allow_inf_nan=False)
    y: float = Field(default=0, ge=0, le=539, allow_inf_nan=False)
    delta: float = Field(default=0, ge=-1000, le=1000, allow_inf_nan=False)
    text: str = Field(default="", max_length=2000)
    key: str = Field(default="", max_length=30)
