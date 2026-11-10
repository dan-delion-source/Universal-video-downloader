import asyncio
from contextlib import suppress
import json
import os
import shutil
import signal
import sys
import time
import uuid
from backend.config import DOWNLOAD_DIR, ROOT, MAX_JOBS, MAX_HISTORY, MAX_PENDING, DOWNLOAD_TIMEOUT
from backend.models import Job, DownloadRequest

TERMINAL = {"complete", "error", "cancelled"}


async def stop_process(process):
    if process.returncode is not None: return
    if os.name == "nt":
        # taskkill /T includes ffmpeg descendants.
        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        with suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def create_worker(payload):
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "backend.worker", cwd=ROOT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name != "nt", limit=4 * 1024 * 1024)
    try:
        process.stdin.write((json.dumps(payload) + "\n").encode())
        await process.stdin.drain()
        process.stdin.close()
        return process
    except BaseException:
        await stop_process(process)
        raise


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.listeners: dict[str, set[asyncio.Queue]] = {}
        self.slots = asyncio.Semaphore(MAX_JOBS)

    def publish(self, job_id, **changes):
        job = self.jobs[job_id]
        for key, value in changes.items(): setattr(job, key, value)
        for queue in self.listeners.get(job_id, set()):
            if queue.full():
                with suppress(asyncio.QueueEmpty): queue.get_nowait()
            queue.put_nowait(job.model_dump())

    def add(self, request: DownloadRequest, cookie_browser=None, browser_auth=None) -> Job:
        if sum(j.status not in TERMINAL for j in self.jobs.values()) >= MAX_PENDING:
            raise ValueError("The download queue is full. Wait for a download to finish.")
        while len(self.jobs) >= MAX_HISTORY:
            old = next((key for key, j in self.jobs.items() if j.status in TERMINAL and not self.listeners.get(key)), None)
            if old is None: break
            self.jobs.pop(old)
            self.listeners.pop(old, None)
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, title=request.title, created_at=time.time())
        self.jobs[job_id] = job
        task = asyncio.create_task(self.run(job_id, request, cookie_browser, browser_auth))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))
        return job

    async def run(self, job_id, request, cookie_browser, browser_auth=None):
        process = None
        try:
            async with self.slots:
                process = await create_worker({**request.model_dump(), "action": "download", "job_id": job_id, "cookie_browser": cookie_browser, "browser_auth": browser_auth})
                async def consume():
                    while line := await process.stdout.readline():
                        event = json.loads(line)
                        if "status" in event: self.publish(job_id, **event)
                    await process.wait()
                await asyncio.wait_for(consume(), DOWNLOAD_TIMEOUT)
                if self.jobs[job_id].status not in TERMINAL:
                    self.publish(job_id, status="error", error="Download stopped before a file was produced.")
        except asyncio.CancelledError:
            self.publish(job_id, status="cancelled", speed=None, eta=None)
            raise
        except asyncio.TimeoutError:
            self.publish(job_id, status="error", error="Download exceeded the two-hour time limit.")
        except Exception:
            self.publish(job_id, status="error", error="Download worker failed. Try scanning the page again.")
        finally:
            if process is not None: await stop_process(process)
            shutil.rmtree(DOWNLOAD_DIR / (".job-" + job_id), ignore_errors=True)

    async def cancel(self, job_id):
        if self.jobs[job_id].status in TERMINAL: return
        self.publish(job_id, status="cancelled", speed=None, eta=None)
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError): await task

    async def close(self):
        for job_id in list(self.tasks): await self.cancel(job_id)
