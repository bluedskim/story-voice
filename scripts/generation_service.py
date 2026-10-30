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

from audio_quality_config import resolve_asr_verify
from generation_backends import GenerationBackend, get_backend
from story_catalog import list_stories, load_story, write_manifest
from default_narration import (
    SYSTEM_USER_ID,
    default_story_audio,
    ensure_default_reference,
)
from user_storage import ensure_user_reference, user_audio_dir, user_story_audio

MANIFEST_PATH = ROOT / "web" / "catalog.json"

MAX_QUEUE_LEN = 2  # pending jobs besides the running one

BUSY_MEMBER_MESSAGE = "이미 만들고 있는 이야기가 있어요. 끝난 뒤에 다시 시도해 주세요."


class MemberBusyError(RuntimeError):
    """A member already has a queued/running generation job (one at a time)."""


class StoryNotFoundError(Exception):
    def __init__(self, story_id: str) -> None:
        self.story_id = story_id
        super().__init__(f"unknown story: {story_id}")


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class GenerationJob:
    job_id: str
    user_id: int
    story_ids: list[str]
    asr_verify: bool = False
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
            "asrVerify": self.asr_verify,
        }


@dataclass
class EnqueueResult:
    job: GenerationJob
    created: bool


class GenerationService:
    def __init__(
        self,
        backend: GenerationBackend | None = None,
        on_catalog_refresh: Callable[[int], None] | None = None,
    ) -> None:
        self._backend = backend or get_backend()
        self._on_catalog_refresh = on_catalog_refresh
        self._queue: Queue[str] = Queue(maxsize=MAX_QUEUE_LEN)
        self._jobs: dict[str, GenerationJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        # Serializes check-then-enqueue so a member can't race two jobs in.
        self._enqueue_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_worker, name="generation-worker", daemon=True)
        self._worker.start()

    @staticmethod
    def catalog_ids() -> set[str]:
        return {s.id for s in list_stories()}

    def _get_job(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _active_story_ids(self, user_id: int) -> set[str]:
        with self._lock:
            active: set[str] = set()
            for jid in self._order:
                job = self._jobs.get(jid)
                if not job or job.user_id != user_id:
                    continue
                if job.state not in {JobState.QUEUED, JobState.RUNNING}:
                    continue
                active.update(job.story_ids)
            return active

    def _find_active_job_for_story(self, user_id: int, story_id: str) -> GenerationJob | None:
        with self._lock:
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if not job or job.user_id != user_id:
                    continue
                if job.state not in {JobState.QUEUED, JobState.RUNNING}:
                    continue
                if story_id in job.story_ids:
                    return job
        return None

    def _find_any_active_job(self, user_id: int) -> GenerationJob | None:
        with self._lock:
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if job and job.user_id == user_id and job.state in {JobState.QUEUED, JobState.RUNNING}:
                    return job
        return None

    def enqueue_story(
        self,
        story_id: str,
        user_id: int,
        *,
        is_admin: bool = False,
        asr_verify_request: bool | None = None,
    ) -> EnqueueResult:
        if story_id not in self.catalog_ids():
            raise StoryNotFoundError(story_id)
        with self._enqueue_lock:
            existing = self._find_active_job_for_story(user_id, story_id)
            if existing:
                return EnqueueResult(job=existing, created=False)
            # One queued/running job per member so nobody can monopolize the worker.
            if user_id != SYSTEM_USER_ID and self._find_any_active_job(user_id):
                raise MemberBusyError(BUSY_MEMBER_MESSAGE)
            return EnqueueResult(
                job=self._enqueue(
                    user_id,
                    [story_id],
                    is_admin=is_admin,
                    asr_verify_request=asr_verify_request,
                ),
                created=True,
            )

    def enqueue_missing_default_stories(self) -> EnqueueResult | None:
        """Generate shared default audio for any catalog story that lacks it."""
        missing = [s.id for s in list_stories() if not default_story_audio(s.id).is_file()]
        if not missing:
            return None
        active = self._active_story_ids(SYSTEM_USER_ID)
        ids = [sid for sid in missing if sid not in active]
        if not ids:
            existing = self._find_any_active_job(SYSTEM_USER_ID)
            if existing:
                return EnqueueResult(job=existing, created=False)
            return None
        return EnqueueResult(
            job=self._enqueue(SYSTEM_USER_ID, ids, is_admin=False, asr_verify_request=False),
            created=True,
        )

    def _enqueue(
        self,
        user_id: int,
        story_ids: list[str],
        *,
        is_admin: bool = False,
        asr_verify_request: bool | None = None,
    ) -> GenerationJob:
        if not story_ids:
            raise ValueError("no stories")
        job_id = str(uuid.uuid4())
        job = GenerationJob(
            job_id=job_id,
            user_id=user_id,
            story_ids=story_ids,
            asr_verify=resolve_asr_verify(asr_verify_request),
        )
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

    def status_snapshot(self, user_id: int | None = None) -> dict:
        with self._lock:
            running = None
            queued = []
            for jid in self._order:
                job = self._jobs.get(jid)
                if not job:
                    continue
                if user_id is not None and job.user_id != user_id:
                    continue
                if job.state == JobState.RUNNING:
                    running = job.to_public()
                elif job.state == JobState.QUEUED:
                    queued.append(job.to_public())
            recent = []
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if not job:
                    continue
                if user_id is not None and job.user_id != user_id:
                    continue
                if job.state in {JobState.DONE, JobState.FAILED}:
                    recent.append(job.to_public())
                if len(recent) >= 5:
                    break
        return {
            "running": running,
            "queued": queued,
            "recent": recent,
            "maxQueue": MAX_QUEUE_LEN,
        }

    def is_busy(self, user_id: int | None = None) -> bool:
        snap = self.status_snapshot(user_id)
        return snap["running"] is not None or len(snap["queued"]) >= MAX_QUEUE_LEN

    def is_generating(self) -> bool:
        """True while TTS worker is actively generating (blocks voice ASR)."""
        with self._lock:
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if job and job.state == JobState.RUNNING:
                    return True
        return False

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
        is_admin = False
        try:
            if job.user_id == SYSTEM_USER_ID:
                ref_wav, ref_txt = ensure_default_reference()
                from default_narration import default_audio_dir

                staging_dir = default_audio_dir() / ".staging"
            else:
                from auth_db import AuthDatabase
                from auth_service import user_is_admin

                db = AuthDatabase()
                user = db.get_user_by_id(job.user_id)
                is_admin = bool(user and user_is_admin(user))
                ref_wav, ref_txt = ensure_user_reference(job.user_id, is_admin)
                staging_dir = user_audio_dir(job.user_id) / ".staging"

            staging_dir.mkdir(parents=True, exist_ok=True)

            for story_id in job.story_ids:
                if story_id not in self.catalog_ids():
                    raise RuntimeError(f"이야기를 찾을 수 없어요: {story_id}")
                story_path = ROOT / "content" / "stories" / f"{story_id}.txt"
                if not story_path.is_file():
                    raise RuntimeError(f"이야기를 찾을 수 없어요: {story_id}")
                story = load_story(story_path)
                job.current_story_id = story_id
                job.chunk_index = 0
                job.chunk_total = 0

                tmp_out = staging_dir / f"{story_id}.{job.job_id}.m4a"
                if job.user_id == SYSTEM_USER_ID:
                    final_out = default_story_audio(story_id)
                else:
                    final_out = user_story_audio(job.user_id, story_id)

                def on_progress(current: int, total: int, _sid: str) -> None:
                    job.chunk_index = current
                    job.chunk_total = total

                self._backend.generate_story(
                    story_id,
                    story.body,
                    tmp_out,
                    on_progress,
                    verify_asr=job.asr_verify,
                    ref_wav=ref_wav,
                    ref_txt=ref_txt,
                )
                final_out.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_out, final_out)

            write_manifest(MANIFEST_PATH)
            if self._on_catalog_refresh and job.user_id != SYSTEM_USER_ID:
                self._on_catalog_refresh(job.user_id)
            job.state = JobState.DONE
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            job.current_story_id = None
