import json
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from backend.main import app, manager
from backend.models import Job


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_health(client):
    result = client.get("/api/health")
    assert result.status_code == 200
    assert isinstance(result.json()["ffmpeg"], bool)
    assert isinstance(result.json()["playwright"], bool)
    assert result.json()["ytdlp_version"]


def test_cross_origin_mutation(client):
    assert client.post("/api/update-engine", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/scan", json={"url": "https://example.org"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_invalid_host(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_json_required(client):
    assert client.post("/api/update-engine", content="anything").status_code == 415


def test_invalid_urls_and_quality(client):
    assert client.post("/api/scan", json={"url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/download", json={"url": "https://example.org", "format_id": "../../x"}).status_code == 400


def test_terminal_sse_replays(client):
    job = Job(id="finished-test", title="Test", status="complete", percent=100, filename="Test.mp4", created_at=time.time())
    manager.jobs[job.id] = job
    try:
        response = client.get(f"/api/jobs/{job.id}/events")
        assert response.headers["content-type"].startswith("text/event-stream")
        data = json.loads(response.text.removeprefix("data: ").strip())
        assert data["filename"] == "Test.mp4" and data["percent"] == 100
    finally:
        manager.jobs.pop(job.id, None)
        manager.listeners.pop(job.id, None)


def test_missing_jobs_and_files(client):
    assert client.get("/api/jobs/missing/events").status_code == 404
    assert client.post("/api/jobs/missing/cancel", json={}).status_code == 404
    assert client.get("/api/files/.hidden.mp4").status_code == 400
    assert client.get("/api/files/not-present.mp4").status_code == 404
    assert client.get("/api/does-not-exist").status_code == 404


def test_scan_worker_result(client):
    class FakeProcess:
        returncode = 0
        async def communicate(self): return (b'{"items": [], "warnings": []}', None)
    async def create(_): return FakeProcess()
    async def stop(_): pass
    with patch("backend.main.create_worker", side_effect=create), patch("backend.main.stop_process", side_effect=stop):
        assert client.post("/api/scan", json={"url": "https://example.org"}).json() == {"items": [], "warnings": []}
