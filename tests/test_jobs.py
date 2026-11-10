"""Exercise queue limits and queued cancellation without network or ffmpeg."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from backend.jobs import JobManager, MAX_PENDING
from backend.models import DownloadRequest


def test_queue_limit_and_cancel_before_start():
    async def scenario():
        manager = JobManager()
        manager.slots = asyncio.Semaphore(0)
        request = DownloadRequest(url="https://example.org/video", title="Example")
        jobs = [manager.add(request) for _ in range(MAX_PENDING)]
        with pytest.raises(ValueError, match="queue is full"): manager.add(request)
        await manager.cancel(jobs[0].id)
        assert manager.jobs[jobs[0].id].status == "cancelled"
        await manager.close()
        assert all(j.status == "cancelled" for j in manager.jobs.values())
    asyncio.run(scenario())


def test_two_active_workers_and_running_cancellation():
    async def scenario():
        manager = JobManager()
        workers = []
        class Process:
            returncode = None
            def __init__(self):
                self.stdout = asyncio.StreamReader()
            async def wait(self):
                self.returncode = 0
        async def create(_):
            process = Process()
            workers.append(process)
            return process
        async def stop(process):
            process.returncode = -9
            process.stdout.feed_eof()
        with patch("backend.jobs.create_worker", side_effect=create), patch("backend.jobs.stop_process", side_effect=stop):
            jobs = [manager.add(DownloadRequest(url="https://example.org/video")) for _ in range(3)]
            for _ in range(10): await asyncio.sleep(0)
            assert len(workers) == 2
            await manager.cancel(jobs[0].id)
            for _ in range(10): await asyncio.sleep(0)
            assert len(workers) == 3
            assert workers[0].returncode == -9
            await manager.close()
    asyncio.run(scenario())


def test_subscriber_queue_is_bounded_and_latest_wins():
    async def scenario():
        manager = JobManager()
        manager.slots = asyncio.Semaphore(0)
        job = manager.add(DownloadRequest(url="https://example.org/video"))
        queue = asyncio.Queue(maxsize=1)
        manager.listeners[job.id] = {queue}
        manager.publish(job.id, percent=10)
        manager.publish(job.id, percent=20)
        assert queue.qsize() == 1 and (await queue.get())["percent"] == 20
        await manager.close()
    asyncio.run(scenario())
