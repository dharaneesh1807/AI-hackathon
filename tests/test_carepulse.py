from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from test_api import account, profile, join


@pytest.fixture
def care(tmp_path):
    # 07:50 IST; first dose is ten minutes in the future.
    now = [int(datetime(2026, 11, 15, 2, 20, tzinfo=timezone.utc).timestamp())]
    app = create_app(f'sqlite:///{tmp_path / "care.db"}', 'test-secret-' + 'x'*40,
                     clock=lambda: now[0], scheduler_secret='scheduler-test-secret')
    with TestClient(app) as c:
        _, owner = account(c, 'patient@example.com')
        pid = profile(c, owner)
        med = {'name': 'Demo medicine', 'dosage': 'As prescribed', 'times': ['08:00']}
        r = c.post(f'/profiles/{pid}/medications', headers=owner, json=med)
        assert r.status_code == 201
        base = f'/profiles/{pid}/carepulse'
        doses = c.get(base+'/doses', headers=owner).json()
        first = min(doses, key=lambda d: d['due_at'])
        assert first['due_at'] == '2026-11-15T02:30:00+00:00'
        yield c, now, owner, pid, base, first, r.json()['id']


def test_due_escalation_and_single_confirmation(care):
    c, now, owner, pid, base, first, _ = care
    path = f'{base}/doses/{first["id"]}/record'
    assert c.post(path, headers=owner, json={'status':'taken'}).status_code == 409
    now[0] += 10*60
    assert c.post(base+'/refresh', headers=owner).json() == {'new_unconfirmed':0}
    now[0] += 31*60
    assert c.post(base+'/refresh', headers=owner).json() == {'new_unconfirmed':1}
    assert c.post(base+'/refresh', headers=owner).json() == {'new_unconfirmed':0}
    assert c.get(base+'/alerts', headers=owner).json()[0]['status'] == 'unconfirmed'
    r = c.post(path, headers=owner, json={'status':'taken'})
    assert r.json()['follow_up'] == 'resolved'
    assert c.post(path, headers=owner, json={'status':'taken'}).status_code == 200
    assert c.post(path, headers=owner, json={'status':'skipped'}).status_code == 409
    assert c.get(base+'/alerts', headers=owner).json() == []
    events = c.get(base+'/timeline', headers=owner).json()
    assert sum(e['action']=='dose_taken' for e in events) == 1
    assert sum(e['action']=='dose_unconfirmed' for e in events) == 1


def test_family_claim_and_resolve_without_false_confirmation(care):
    c, now, owner, pid, base, first, _ = care
    _, family = account(c, 'family@example.com')
    _, care2 = account(c, 'caregiver@example.com')
    _, stranger = account(c, 'stranger@example.com')
    join(c, owner, family, pid, 'family@example.com', 'family')
    join(c, owner, care2, pid, 'caregiver@example.com', 'caregiver')
    now[0] += 41*60
    c.post(base+'/refresh', headers=owner)
    path = f'{base}/doses/{first["id"]}'
    assert c.get(base+'/doses', headers=stranger).status_code == 404
    assert c.post(path+'/record', headers=family, json={'status':'taken'}).status_code == 403
    assert c.post(path+'/follow-up', headers=stranger, json={'action':'claim'}).status_code == 404
    assert c.post(path+'/follow-up', headers=family, json={'action':'claim'}).status_code == 200
    assert c.post(path+'/follow-up', headers=care2, json={'action':'claim'}).status_code == 409
    assert c.post(path+'/follow-up', headers=family, json={'action':'resolve'}).status_code == 422
    r = c.post(path+'/follow-up', headers=family, json={'action':'resolve','note':'Spoke to patient; dose not confirmed'})
    assert r.json()['status'] == 'unconfirmed'
    assert r.json()['follow_up'] == 'resolved'
    assert c.get(base+'/alerts', headers=family).json() == []
    assert c.post(path+'/record', headers=care2, json={'status':'taken'}).status_code == 422


def test_schedule_edit_preserves_history(care):
    c, now, owner, pid, base, first, mid = care
    now[0] += 10*60
    assert c.post(f'{base}/doses/{first["id"]}/record', headers=owner, json={'status':'taken'}).status_code == 200
    r = c.put(f'/profiles/{pid}/medications/{mid}', headers=owner,
              json={'name':'Changed name','dosage':'As prescribed','times':['09:00']})
    assert r.status_code == 200
    rows = c.get(base+'/doses', headers=owner).json()
    old = next(d for d in rows if d['id']==first['id'])
    assert old['medication_name'] == 'Demo medicine' and old['status']=='taken'
    assert all(d['due_at'].endswith('03:30:00+00:00') for d in rows if d['status']=='scheduled')
    assert c.delete(f'/profiles/{pid}/medications/{mid}', headers=owner).status_code == 204
    assert c.get(base+'/doses', headers=owner).json() == [old]


def test_scheduler_auth_and_idempotency(care):
    c, now, owner, pid, base, first, _ = care
    now[0] += 41*60
    assert c.post('/internal/carepulse/refresh').status_code == 401
    assert c.post('/internal/carepulse/refresh', headers={'X-Scheduler-Token':'wrong'}).status_code == 401
    headers = {'X-Scheduler-Token':'scheduler-test-secret'}
    assert c.post('/internal/carepulse/refresh', headers=headers).json()['new_unconfirmed'] == 1
    assert c.post('/internal/carepulse/refresh', headers=headers).json()['new_unconfirmed'] == 0


def test_revocation_releases_claim(care):
    c, now, owner, pid, base, first, _ = care
    uid, family = account(c, 'family@example.com')
    join(c, owner, family, pid, 'family@example.com', 'family')
    now[0] += 41*60
    c.post(base+'/refresh', headers=owner)
    path = f'{base}/doses/{first["id"]}/follow-up'
    assert c.post(path, headers=family, json={'action':'claim'}).status_code == 200
    assert c.delete(f'/profiles/{pid}/members/{uid}', headers=owner).status_code == 204
    assert c.get(base+'/alerts', headers=owner).json()[0]['follow_up']=='open'
    assert c.post(path, headers=family, json={'action':'claim'}).status_code == 404
