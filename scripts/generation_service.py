"""Single-worker generation queue with atomic audio replace."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "data" / "audio"
STAGING_DIR = AUDIO_DIR / ".staging"

from generation_backends import GenerationBackend, get_backend
from story_catalog import list_stories, load_story, write_manifest

MANIFEST_PATH = ROOT / "web" / "catalog.json"

MAX_QUEUE_LEN = 2  # pending jobs besides the running one


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class GenerationJob:
    job_id: str
    story_ids: list[str]
    state: JobState = JobState.QUEUED
    current_story_id: str | None = None
    chunk_index: int = 0
    chunk_total: int = 0
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_public(self) -> dict:
        return {
            "jobId": self.job_id,
            "storyIds": self.story_ids,
            "state": self.state.value,
            "currentStoryId": self.current_story_id,
            "chunkIndex": self.chunk_index,
            "chunkTotal": self.chunk_total,
            "error": self.error,
        }


class GenerationService:
    def __init__(
        self,
        backend: GenerationBackend | None = None,
        on_catalog_refresh: Callable[[], None] | None = None,
    ) -> None:
        self._backend = backend or get_backend()
        self._on_catalog_refresh = on_catalog_refresh
        self._queue: Queue[str] = Queue(maxsize=MAX_QUEUE_LEN)
        self._jobs: dict[str, GenerationJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_worker, name="generation-worker", daemon=True)
        self._worker.start()

    def _get_job(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def enqueue_story(self, story_id: str) -> GenerationJob:
        return self._enqueue([story_id])

    def enqueue_all(self) -> GenerationJob:
        ids = [s.id for s in list_stories()]
        return self._enqueue(ids)

    def _enqueue(self, story_ids: list[str]) -> GenerationJob:
        if not story_ids:
            raise ValueError("no stories")
        job_id = str(uuid.uuid4())
        job = GenerationJob(job_id=job_id, story_ids=story_ids)
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            if len(self._order) > 20:
                for old_id in self._order[:-20]:
                    self._jobs.pop(old_id, None)
                self._order = self._order[-20:]
        try:
            self._queue.put_nowait(job_id)
        except Full:
            job.state = JobState.FAILED
            job.error = "대기열이 가득 찼어요. 잠시 후 다시 시도해 주세요."
            raise RuntimeError(job.error)
        return job

    def status_snapshot(self) -> dict:
        with self._lock:
            running = None
            queued = []
            for jid in self._order:
                job = self._jobs.get(jid)
                if not job:
                    continue
                if job.state == JobState.RUNNING:
                    running = job.to_public()
                elif job.state == JobState.QUEUED:
                    queued.append(job.to_public())
            recent = []
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if job and job.state in {JobState.DONE, JobState.FAILED}:
                    recent.append(job.to_public())
                if len(recent) >= 5:
                    break
        return {
            "running": running,
            "queued": queued,
            "recent": recent,
            "maxQueue": MAX_QUEUE_LEN,
        }

    def is_busy(self) -> bool:
        snap = self.status_snapshot()
        return snap["running"] is not None or len(snap["queued"]) >= MAX_QUEUE_LEN

    def _run_worker(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=0.5)
            except Empty:
                continue
            job = self._get_job(job_id)
            if not job:
                continue
            self._process_job(job)

    def _process_job(self, job: GenerationJob) -> None:
        job.state = JobState.RUNNING
        try:
            from voice_service import has_reference

            if not has_reference():
                raise RuntimeError("목소리 샘플이 없어요. 먼저 목소리를 저장해 주세요.")

            for story_id in job.story_ids:
                story_path = ROOT / "content" / "stories" / f"{story_id}.txt"
                if not story_path.is_file():
                    raise RuntimeError(f"이야기를 찾을 수 없어요: {story_id}")
                story = load_story(story_path)
                job.current_story_id = story_id
                job.chunk_index = 0
                job.chunk_total = 0

                STAGING_DIR.mkdir(parents=True, exist_ok=True)
                tmp_out = STAGING_DIR / f"{story_id}.{job.job_id}.m4a"
                final_out = AUDIO_DIR / f"{story_id}.m4a"

                def on_progress(current: int, total: int, _sid: str) -> None:
                    job.chunk_index = current
                    job.chunk_total = total

                self._backend.generate_story(story_id, story.body, tmp_out, on_progress)
                os.replace(tmp_out, final_out)

            write_manifest(MANIFEST_PATH)
            if self._on_catalog_refresh:
                self._on_catalog_refresh()
            job.state = JobState.DONE
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            job.current_story_id = None
