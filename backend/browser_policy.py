"""Small browser policies, kept independent of the optional Playwright package."""
from urllib.parse import urlsplit
from backend.security import parse_url

WIDTH, HEIGHT = 960, 540
MAX_TABS = 5
KEYS = {"Enter", "Tab", "Shift+Tab", "Escape", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", "ControlOrMeta+A", "Space"}


def media_response(url: str, content_type: str) -> bool:
    try: path = parse_url(url).path.lower()
    except ValueError: return False
    kind = content_type.split(";", 1)[0].strip().lower()
    if path.endswith((".ts", ".m4s", ".aac", ".m4a")) or kind in {"video/mp2t", "video/iso.segment"}:
        return False  # Individual stream fragments are not downloadable videos.
    return path.endswith((".mp4", ".webm", ".mov", ".m4v", ".m3u8", ".mpd")) or kind.startswith("video/") or "mpegurl" in kind or kind == "application/dash+xml"


class TabPolicy:
    def __init__(self):
        self.tabs: dict[str, dict] = {}
        self.active: str | None = None

    def add(self, tab_id: str, initial=False):
        if len(self.tabs) >= MAX_TABS: raise ValueError("Close a tab before opening another.")
        self.tabs[tab_id] = {"id": tab_id, "url": "about:blank", "title": "New tab", "pending": not initial}
        if initial: self.active = tab_id

    def navigation(self, tab_id: str, url: str) -> bool:
        parse_url(url)
        tab = self.tabs[tab_id]
        tab["url"] = url
        return not tab["pending"]

    def activate(self, tab_id: str):
        tab = self.tabs[tab_id]
        parse_url(tab["url"])
        tab["pending"] = False
        self.active = tab_id

    def remove(self, tab_id: str):
        self.tabs.pop(tab_id, None)
        if self.active == tab_id:
            self.active = next((key for key, tab in self.tabs.items() if not tab["pending"]), None)

    def snapshot(self):
        return {"active_tab": self.active,
                "tabs": [dict(tab) for tab in self.tabs.values() if not tab["pending"]],
                "popups": [dict(tab) for tab in self.tabs.values() if tab["pending"]]}


class NavigationPolicy:
    """Page scripts propose destinations; only app controls can approve them."""
    def __init__(self):
        self.pending: dict[str, dict] = {}
        self.permitted: dict[str, str] = {}

    @staticmethod
    def normalized(url: str):
        import httpx
        parse_url(url)
        return str(httpx.URL(url).copy_with(fragment=None))

    def propose(self, source_tab: str, url: str, kind="navigate"):
        import uuid
        self.normalized(url)
        for intent in self.pending.values():
            if intent["source_tab"] == source_tab and intent["url"] == url:
                return intent["id"]
        if len(self.pending) >= 4:
            return None  # Excess proposals are still blocked, never auto-approved.
        intent_id = uuid.uuid4().hex
        self.pending[intent_id] = {"id": intent_id, "source_tab": source_tab, "url": url,
                                   "kind": kind, "hostname": urlsplit(url).hostname}
        return intent_id

    def grant(self, tab_id: str, url: str):
        self.permitted[tab_id] = self.normalized(url)

    def consume(self, tab_id: str, url: str):
        expected = self.permitted.pop(tab_id, None)
        return expected is not None and expected == self.normalized(url)

    def revoke(self, tab_id: str):
        self.permitted.pop(tab_id, None)

    def resolve(self, intent_id: str):
        return self.pending.pop(intent_id)

    def remove_tab(self, tab_id: str):
        self.revoke(tab_id)
        self.pending = {key: item for key, item in self.pending.items() if item["source_tab"] != tab_id}

    def snapshot(self):
        return [dict(intent) for intent in self.pending.values()]
