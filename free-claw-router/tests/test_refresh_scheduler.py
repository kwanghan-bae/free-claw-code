import pytest
from router.catalog.refresh.scheduler import CronScheduler, CronJob

def test_register_and_list_jobs():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={"provider": "openrouter"}))
    s.register(CronJob(job_id="j2", cron_expr="0 4 * * *", payload={"provider": "groq"}))
    jobs = s.list_jobs()
    assert {j.job_id for j in jobs} == {"j1", "j2"}

def test_duplicate_job_id_raises():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={}))
    with pytest.raises(ValueError):
        s.register(CronJob(job_id="j1", cron_expr="0 5 * * *", payload={}))

def test_unregister_removes_job():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={}))
    s.unregister("j1")
    assert s.list_jobs() == []
