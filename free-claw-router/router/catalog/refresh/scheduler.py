from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

@dataclass
class CronJob:
    job_id: str
    cron_expr: str
    payload: dict

class CronScheduler:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._jobs: dict[str, CronJob] = {}
        self._handler: Callable[[CronJob], None] | None = None
        self._scheduler.start()

    def bind(self, handler: Callable[[CronJob], None]) -> None:
        self._handler = handler

    def register(self, job: CronJob) -> None:
        if job.job_id in self._jobs:
            raise ValueError(f"duplicate job_id: {job.job_id}")
        trigger = CronTrigger.from_crontab(job.cron_expr)
        def runner():
            if self._handler is not None:
                self._handler(job)
        self._scheduler.add_job(runner, trigger=trigger, id=job.job_id, replace_existing=False)
        self._jobs[job.job_id] = job

    def unregister(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())
