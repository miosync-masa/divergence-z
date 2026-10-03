"""ジョブ管理。

  queued → running → succeeded / failed / cancelled
  pipeline だけ: running → awaiting_review → (resume) → running

イベントはジョブごとの連番付きリストに追記し、SSE は Last-Event-ID から続きを読む。
LLM 呼び出しは I/O 待ちなのでスレッドプールで回す（既定 2 本）。
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from divergence_z.core import CancelToken, Cancelled, Keys, classify_error

from .projects import Project

TERMINAL = {"succeeded", "failed", "cancelled"}


class JobInputError(Exception):
    """パラメータ・プロジェクト状態の不備（UI 側で直せるもの）"""
MAX_EVENTS = 2000


@dataclass
class Event:
    id: int
    type: str            # progress | status | artifact | done
    data: Dict[str, Any]
    time: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type, "data": self.data, "time": self.time}


@dataclass
class Job:
    id: str
    type: str
    project: Project
    params: Dict[str, Any]
    status: str = "queued"
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    error: Optional[Dict[str, str]] = None
    result: Optional[Dict[str, Any]] = None
    usage: Dict[str, int] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    cancel_token: CancelToken = field(default_factory=CancelToken)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _resume: bool = False
    _seq: int = 0

    # --- events ----------------------------------------------------------------

    def emit(self, type_: str, **data: Any) -> None:
        with self._cond:
            self._seq += 1
            self.events.append(Event(self._seq, type_, data))
            if len(self.events) > MAX_EVENTS:
                self.events = self.events[-MAX_EVENTS:]
            self.updated = time.time()
            self._cond.notify_all()

    def progress(self, message: str = "", **data: Any) -> None:
        self.emit("progress", message=message, **data)

    def artifact(self, kind: str, path: str, **data: Any) -> None:
        self.emit("artifact", kind=kind, path=path, **data)

    def set_status(self, status: str, **data: Any) -> None:
        self.status = status
        self.emit("status", status=status, **data)

    def events_after(self, last_id: int) -> List[Event]:
        with self._cond:
            return [e for e in self.events if e.id > last_id]

    # --- cancel / review gate ----------------------------------------------------

    def check(self) -> None:
        self.cancel_token.check()

    def wait_for_review(self, reason: str, **data: Any) -> None:
        """人物表の確認待ち。resume で再開、cancel で中止"""
        self.set_status("awaiting_review", reason=reason, **data)
        with self._cond:
            while not self._resume and not self.cancel_token.cancelled:
                self._cond.wait(timeout=1.0)
            self._resume = False
        self.check()
        self.set_status("running")

    def resume(self) -> bool:
        with self._cond:
            if self.status != "awaiting_review":
                return False
            self._resume = True
            self._cond.notify_all()
            return True

    def cancel(self) -> None:
        self.cancel_token.cancel()
        with self._cond:
            self._cond.notify_all()

    # --- views -------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type, "project_id": self.project.id,
                "params": self.params, "status": self.status, "created": self.created,
                "updated": self.updated, "error": self.error, "result": self.result,
                "usage": self.usage, "last_event_id": self._seq}


# runner(job, keys) -> result dict
Runner = Callable[[Job, Keys], Dict[str, Any]]


class JobManager:
    def __init__(self, runners: Dict[str, Runner], max_workers: int = 2):
        self.runners = runners
        self.jobs: Dict[str, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dz-job")
        self._lock = threading.Lock()

    def submit(self, type_: str, project: Project, params: Dict[str, Any], keys: Keys) -> Job:
        if type_ not in self.runners:
            raise KeyError(type_)
        job = Job(uuid.uuid4().hex[:12], type_, project, params)
        with self._lock:
            self.jobs[job.id] = job
        job.emit("status", status="queued")
        # キーはジョブ開始時点のスナップショットを渡す（途中でキーが変わっても影響しない）
        snapshot = Keys(keys.openai, keys.anthropic, keys.openai_base_url)
        self.pool.submit(self._run, job, snapshot)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list(self, project_id: Optional[str] = None) -> List[Job]:
        return [j for j in self.jobs.values() if project_id is None or j.project.id == project_id]

    def _run(self, job: Job, keys: Keys) -> None:
        if job.cancel_token.cancelled:
            job.set_status("cancelled")
            job.emit("done", status="cancelled")
            self._persist(job)
            return
        job.set_status("running")
        try:
            job.result = self.runners[job.type](job, keys)
            job.status = "succeeded"
        except Cancelled:
            job.status = "cancelled"
        except JobInputError as exc:
            job.status = "failed"
            job.error = {"code": "invalid_input", "message": str(exc), "type": "JobInputError"}
        except Exception as exc:  # noqa: BLE001 — ジョブの失敗は UI に返す
            job.status = "failed"
            job.error = {"code": classify_error(exc), "message": str(exc)[:2000],
                         "type": type(exc).__name__}
            job.progress(traceback.format_exc(limit=3), level="debug")
        job.emit("done", status=job.status, result=job.result, error=job.error, usage=job.usage)
        self._persist(job)

    def _persist(self, job: Job) -> None:
        try:
            job.project.jobs_dir.mkdir(parents=True, exist_ok=True)
            record = {**job.summary(), "events": [e.to_dict() for e in job.events[-200:]]}
            (job.project.jobs_dir / f"{job.id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass

    def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.status not in TERMINAL:
                job.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
