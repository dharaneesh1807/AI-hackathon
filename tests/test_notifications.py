from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from test_api import account, join, profile

from backend.main import create_app


@pytest.fixture
def reminders(tmp_path):
    now = [int(datetime(2026, 11, 15, 2, 20, tzinfo=timezone.utc).timestamp())]
    app = create_app(
        f"sqlite:///{tmp_path / 'mail.db'}",
        "test-secret-" + "x" * 40,
        clock=lambda: now[0],
        scheduler_secret="test-scheduler",
        demo_email_allowlist=("owner@example.com", "family@example.com"),
    )
    with TestClient(app) as c:
        _, owner = account(c, "owner@example.com")
        fid, family = account(c, "family@example.com")
        _, stranger = account(c, "other@example.com")
        pid = profile(c, owner)
        join(c, owner, family, pid, "family@example.com", "family")
        yield c, now, owner, family, stranger, fid, pid


SCHED = {"X-Scheduler-Token": "test-scheduler"}


def test_reminders_opt_in_delivery_and_dedup(reminders):
    c, now, owner, family, stranger, fid, pid = reminders
    pref = f"/profiles/{pid}/email-reminders"
    med = {"name": "PRIVATE medicine", "dosage": "PRIVATE dose", "times": ["08:00"]}
    assert (
        c.post(f"/profiles/{pid}/medications", headers=owner, json=med).status_code
        == 201
    )
    assert c.post("/internal/email/dispatch").status_code == 401
    assert c.post("/internal/email/dispatch", headers=SCHED).json()["messages"] == []
    assert c.put(pref, headers=stranger, json={"enabled": True}).status_code == 404
    assert c.put(pref, headers=owner, json={"enabled": True}).status_code == 200
    assert c.put(pref, headers=family, json={"enabled": True}).status_code == 200
    messages = c.post("/internal/email/dispatch", headers=SCHED).json()["messages"]
    assert len(messages) == 1 and messages[0]["to"] == "owner@example.com"
    m = messages[0]
    assert "PRIVATE" not in str(m)
    path = f"/internal/email/{m['id']}/result"
    assert c.post(path, headers=SCHED, json={"status": "sent"}).status_code == 200
    assert c.post(path, headers=SCHED, json={"status": "sent"}).status_code == 200
    assert c.post(path, headers=SCHED, json={"status": "failed"}).status_code == 409
    assert c.get(pref, headers=owner).json()["recent"][0]["status"] == "sent"
    assert c.post("/internal/email/dispatch", headers=SCHED).json()["messages"] == []
    now[0] += 41 * 60
    alerts = c.post("/internal/email/dispatch", headers=SCHED).json()["messages"]
    assert {m["to"] for m in alerts} == {"owner@example.com", "family@example.com"}
    assert all("follow-up" in m["subject"] for m in alerts)
    assert c.post("/internal/email/dispatch", headers=SCHED).json()["messages"] == []


def test_appointment_reminders_and_revocation(reminders):
    c, now, owner, family, stranger, fid, pid = reminders
    pref = f"/profiles/{pid}/email-reminders"
    assert c.put(pref, headers=owner, json={"enabled": True}).status_code == 200
    assert c.put(pref, headers=family, json={"enabled": True}).status_code == 200
    other_pid = profile(c, stranger)
    assert (
        c.put(
            f"/profiles/{other_pid}/email-reminders",
            headers=stranger,
            json={"enabled": True},
        ).status_code
        == 403
    )
    assert c.delete(f"/profiles/{pid}/members/{fid}", headers=owner).status_code == 204
    appointment = {
        "title": "PRIVATE title",
        "doctor": "PRIVATE doctor",
        "starts_at": "2026-11-15T05:00:00Z",
    }
    assert (
        c.post(
            f"/profiles/{pid}/appointments", headers=owner, json=appointment
        ).status_code
        == 201
    )
    messages = c.post("/internal/email/dispatch", headers=SCHED).json()["messages"]
    assert len(messages) == 1 and messages[0]["to"] == "owner@example.com"
    assert "appointment" in messages[0]["subject"] and "PRIVATE" not in str(messages)
    assert c.get(pref, headers=family).status_code == 404
