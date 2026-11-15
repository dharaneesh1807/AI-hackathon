import pytest
from fastapi.testclient import TestClient
from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(f'sqlite:///{tmp_path / "test.db"}', 'test-only-secret-' + 'x' * 40)
    with TestClient(app) as c:
        yield c


def account(c, email):
    data = {'email': email, 'password': 'not-a-real-password-123'}
    response = c.post('/auth/register', json={**data, 'name': email.split('@')[0]})
    assert response.status_code == 201
    uid = response.json()['id']
    token = c.post('/auth/login', json=data).json()['access_token']
    return uid, {'Authorization': 'Bearer ' + token}


def profile(c, headers):
    r = c.post('/profiles', json={'name': 'Demo patient'}, headers=headers)
    assert r.status_code == 201
    return r.json()['id']


def join(c, owner, member, pid, email, role):
    invite = c.post(f'/profiles/{pid}/invitations', headers=owner, json={'email': email, 'role': role})
    assert invite.status_code == 201
    code = invite.json()['code']
    assert c.post('/care-circle/join', headers=member, json={'code': code}).status_code == 200
    assert c.post('/care-circle/join', headers=member, json={'code': code}).status_code == 400


MED = {'name': 'Demo medicine', 'dosage': 'As prescribed', 'times': ['08:00', '20:00']}
APPT = {'title': 'Routine check-up', 'doctor': 'Demo doctor', 'starts_at': '2027-01-01T10:30:00+05:30'}


def test_health_and_auth(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/profiles').status_code == 401
    _, auth = account(client, 'patient@example.com')
    assert client.get('/auth/me', headers=auth).json()['email'] == 'patient@example.com'
    assert client.post('/auth/login', json={'email': 'patient@example.com', 'password': 'wrong'}).status_code == 401
    assert client.get('/profiles', headers={'Authorization': 'Bearer bad'}).status_code == 401


def test_medication_crud_and_isolation(client):
    _, owner = account(client, 'owner@example.com')
    _, other = account(client, 'other@example.com')
    pid = profile(client, owner)
    other_pid = profile(client, other)
    path = f'/profiles/{pid}/medications'
    response = client.post(path, headers=owner, json=MED)
    assert response.status_code == 201
    mid = response.json()['id']
    assert client.get(path, headers=other).status_code == 404
    assert client.put(f'/profiles/{other_pid}/medications/{mid}', headers=other, json=MED).status_code == 404
    assert client.post(path, headers=owner, json={**MED, 'times': ['25:00']}).status_code == 422
    assert client.put(f'{path}/{mid}', headers=owner, json={**MED, 'name': 'Updated'}).json()['name'] == 'Updated'
    assert client.get(path, headers=owner).json()[0]['name'] == 'Updated'
    assert client.delete(f'{path}/{mid}', headers=owner).status_code == 204
    assert client.get(path, headers=owner).json() == []


def test_passcodes_roles_and_revocation(client):
    _, owner = account(client, 'owner@example.com')
    family_id, family = account(client, 'family@example.com')
    _, caregiver = account(client, 'care@example.com')
    pid = profile(client, owner)
    invitation = client.post(f'/profiles/{pid}/invitations', headers=owner, json={'email': 'family@example.com', 'role': 'family'}).json()
    assert client.post('/care-circle/join', headers=caregiver, json={'code': invitation['code']}).status_code == 400
    assert client.post('/care-circle/join', headers=family, json={'code': invitation['code']}).status_code == 200
    assert client.post('/care-circle/join', headers=family, json={'code': invitation['code']}).status_code == 400
    assert client.get(f'/profiles/{pid}/medications', headers=family).status_code == 200
    assert client.post(f'/profiles/{pid}/medications', headers=family, json=MED).status_code == 403
    join(client, owner, caregiver, pid, 'care@example.com', 'caregiver')
    assert client.post(f'/profiles/{pid}/medications', headers=caregiver, json=MED).status_code == 201
    assert client.delete(f'/profiles/{pid}/members/{family_id}', headers=owner).status_code == 204
    assert client.get(f'/profiles/{pid}/medications', headers=family).status_code == 404


def test_appointments_crud(client):
    _, owner = account(client, 'owner@example.com')
    pid = profile(client, owner)
    path = f'/profiles/{pid}/appointments'
    r = client.post(path, headers=owner, json=APPT)
    assert r.status_code == 201
    assert r.json()['starts_at'] == '2027-01-01T05:00:00+00:00'
    aid = r.json()['id']
    assert client.put(f'{path}/{aid}', headers=owner, json={**APPT, 'doctor': 'New doctor'}).json()['doctor'] == 'New doctor'
    assert len(client.get(path, headers=owner).json()) == 1
    assert client.delete(f'{path}/{aid}', headers=owner).status_code == 204
    assert client.get(path, headers=owner).json() == []
    assert client.post(path, headers=owner, json={**APPT, 'starts_at': '2027-01-01T10:30:00'}).status_code == 422


def test_input_validation(client):
    assert client.post('/auth/register', json={'name': 'Demo', 'email': 'bad', 'password': 'short'}).status_code == 422
    _, owner = account(client, 'owner@example.com')
    assert client.post('/profiles', headers=owner, json={'name': 'Demo', 'timezone': 'Not/AZone'}).status_code == 422
