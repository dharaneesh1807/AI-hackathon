from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from test_api import account, join, profile

from backend.main import create_app

SCHED = {"X-Scheduler-Token": "test-scheduler"}


@pytest.fixture
def advanced(tmp_path):
    now = [int(datetime(2026, 11, 15, 2, 20, tzinfo=timezone.utc).timestamp())]
    app = create_app(
        f"sqlite:///{tmp_path / 'advanced.db'}",
        "test-secret-" + "x" * 40,
        clock=lambda: now[0],
        scheduler_secret="test-scheduler",
        voice_recipients={
            "owner@example.com": "+12025550123",
            "family@example.com": "+12025550124",
        },
    )
    with TestClient(app) as c:
        _, owner = account(c, "owner@example.com")
        _, family = account(c, "family@example.com")
        _, outsider = account(c, "outsider@example.com")
        pid = profile(c, owner)
        join(c, owner, family, pid, "family@example.com", "family")
        yield c, now, owner, family, outsider, pid


def add_med(c, owner, pid, times=["08:00"]):
    return c.post(
        f"/profiles/{pid}/medications",
        headers=owner,
        json={"name": "Demo med", "dosage": "Demo dose", "times": times},
    ).json()["id"]


def test_supply_permissions_decrement_idempotence_report(advanced):
    c, now, owner, family, outsider, pid = advanced
    mid = add_med(c, owner, pid)
    p = f"/profiles/{pid}"
    path = p + f"/supplies/{mid}"
    assert c.get(p + "/supplies", headers=outsider).status_code == 404
    assert (
        c.put(
            path, headers=family, json={"remaining": 6, "threshold_days": 7}
        ).status_code
        == 403
    )
    assert c.put(path, headers=owner, json={"remaining": -1}).status_code == 422
    assert c.put(
        path, headers=owner, json={"remaining": 6, "threshold_days": 7}
    ).json()["low"]
    now[0] += 11 * 60
    c.post(p + "/carepulse/refresh", headers=owner)
    dose = next(
        d
        for d in c.get(p + "/carepulse/doses", headers=owner).json()
        if d["status"] == "due"
    )
    for _ in range(2):
        assert (
            c.post(
                p + f"/carepulse/doses/{dose['id']}/record",
                headers=owner,
                json={"status": "taken"},
            ).status_code
            == 200
        )
    assert c.get(p + "/supplies", headers=owner).json()[0]["remaining"] == 5
    report = c.get(p + "/care-report", headers=family).json()
    assert report["counts"]["taken"] == 1 and report["confirmed_percent"] == 100
    assert c.get(p + "/care-report", headers=outsider).status_code == 404
    assert c.get(p + "/care-report?days=31", headers=owner).status_code == 422
    assert c.delete(p + f"/medications/{mid}", headers=owner).status_code == 204
    assert c.get(p + "/supplies", headers=owner).json() == []
    assert c.get(p + "/care-report", headers=owner).json()["counts"]["taken"] == 1


def test_voice_threshold_auth_optin_and_dedup(advanced):
    c, now, owner, family, outsider, pid = advanced
    p = f"/profiles/{pid}"
    add_med(c, owner, pid)
    assert c.post("/internal/voice/dispatch").status_code == 401
    assert (
        c.put(
            p + "/voice-reminders", headers=outsider, json={"enabled": True}
        ).status_code
        == 404
    )
    assert (
        c.put(p + "/voice-reminders", headers=owner, json={"enabled": True}).status_code
        == 200
    )
    assert (
        c.get(p + "/voice-reminders", headers=owner).json()["number_ending"] == "0123"
    )
    now[0] += 69 * 60  # 59 minutes overdue
    assert c.post("/internal/voice/dispatch", headers=SCHED).json()["calls"] == []
    now[0] += 60
    calls = c.post("/internal/voice/dispatch", headers=SCHED).json()["calls"]
    assert len(calls) == 1 and calls[0]["to"] == "+12025550123"
    path = f"/internal/voice/{calls[0]['id']}/result"
    assert c.post(path, headers=SCHED, json={"status": "accepted"}).status_code == 200
    assert c.post(path, headers=SCHED, json={"status": "failed"}).status_code == 409
    assert c.post("/internal/voice/dispatch", headers=SCHED).json()["calls"] == []
    assert (
        c.get(p + "/voice-reminders", headers=owner).json()["recent"][0]["status"]
        == "accepted"
    )
    assert c.get(p + "/voice-reminders", headers=family).json()["recent"] == []


def test_voice_claimed_and_confirmed_are_not_dispatched(advanced):
    c, now, owner, family, outsider, pid = advanced
    p = f"/profiles/{pid}"
    add_med(c, owner, pid, ["08:00", "08:10"])
    c.put(p + "/voice-reminders", headers=owner, json={"enabled": True})
    now[0] += 81 * 60
    c.post(p + "/carepulse/refresh", headers=owner)
    doses = c.get(p + "/carepulse/alerts", headers=owner).json()
    assert len(doses) == 2
    assert (
        c.post(
            p + f"/carepulse/doses/{doses[0]['id']}/record",
            headers=owner,
            json={"status": "taken"},
        ).status_code
        == 200
    )
    assert (
        c.post(
            p + f"/carepulse/doses/{doses[1]['id']}/follow-up",
            headers=family,
            json={"action": "claim"},
        ).status_code
        == 200
    )
    assert c.post("/internal/voice/dispatch", headers=SCHED).json()["calls"] == []


def test_voice_approval_and_revocation(advanced):
    c, now, owner, family, outsider, pid = advanced
    p = f"/profiles/{pid}"
    other = profile(c, outsider)
    assert (
        c.put(
            f"/profiles/{other}/voice-reminders",
            headers=outsider,
            json={"enabled": True},
        ).status_code
        == 403
    )
    c.put(p + "/voice-reminders", headers=family, json={"enabled": True})
    member = next(
        m for m in c.get(p + "/members", headers=owner).json() if m["role"] == "family"
    )
    assert (
        c.delete(p + f"/members/{member['user_id']}", headers=owner).status_code == 204
    )
    assert c.get(p + "/voice-reminders", headers=family).status_code == 404
    add_med(c, owner, pid)
    now[0] += 71 * 60
    assert c.post("/internal/voice/dispatch", headers=SCHED).json()["calls"] == []
