import asyncio
from datetime import date

import pytest

from servicetitan_mcp_server import get_jobs_by_type, _scrub_job
from query_validator import JobsByTypeQuery


class DummyClient:
    def __init__(self, settings):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, module, path, params=None):
        # This dummy is not used directly by tests which patch _fetch_all_pages
        return {"data": []}


@pytest.mark.asyncio
async def test_jobs_by_type_input_validation(monkeypatch):
    # Missing job_types should raise via validation
    with pytest.raises(Exception):
        JobsByTypeQuery(job_types=" ")


@pytest.mark.asyncio
async def test_get_jobs_by_type_filters_and_output(monkeypatch):
    # Prepare fake data for job-types, jobs, appointments, technicians, business-units
    fake_job_types = [
        {"id": 1, "name": "GO BACK"},
        {"id": 2, "name": "RPR"},
    ]

    fake_jobs = [
        {"id": 101, "jobNumber": "12345", "jobTypeId": 1, "jobStatus": "Completed", "completedOn": "2025-12-03T12:00:00Z", "total": 0.0, "businessUnitId": 10, "technicianId": 201},
        {"id": 102, "jobNumber": "12346", "jobTypeId": 2, "jobStatus": "Completed", "completedOn": "2025-12-04T12:00:00Z", "total": 100.0, "businessUnitId": 11, "technicianId": 202},
    ]

    fake_appts = [
        {"id": 1001, "jobId": 101, "assignedTechnicians": [{"technicianId": 201, "role": "Primary", "isOriginal": True}]},
        {"id": 1002, "jobId": 102, "assignedTechnicians": [{"technicianId": 202, "role": "Primary"}]},
    ]

    fake_techs = [{"id": 201, "name": "Freddy G"}, {"id": 202, "name": "Jason"}]
    fake_bus = [{"id": 10, "name": "Slab"}, {"id": 11, "name": "Pool"}]

    async def fake_fetch_all_pages(client, module, path, params, max_records=1000):
        if path == "/job-types":
            return fake_job_types
        if path == "/jobs":
            return fake_jobs
        if path == "/appointments":
            return fake_appts
        if path == "/technicians":
            return fake_techs
        if path == "/business-units":
            return fake_bus
        return []

    monkeypatch.setattr("servicetitan_mcp_server._fetch_all_pages", fake_fetch_all_pages)

    # Call the tool to request GO BACK jobs only
    out = await get_jobs_by_type("GO BACK", start_date="2025-11-22", end_date="2026-02-19")

    assert "GO BACK Jobs" in out
    assert "Job #12345" in out
    assert "Freddy G" in out
    assert "total_jobs: 1" in out or "total_jobs:  1" in out
    assert "$0.00" in out

    # Request a job type that doesn't exist -> user-facing error
    out2 = await get_jobs_by_type("NONEXISTENT", start_date="2025-11-22", end_date="2026-02-19")
    assert "Unknown job type" in out2 or "Unknown job type(s)" in out2
