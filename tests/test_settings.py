from test_api import client, account, profile, join


def test_display_name_is_authenticated_and_persistent(client):
    _, auth = account(client, 'owner@example.com')
    _, other = account(client, 'other@example.com')
    assert client.patch('/auth/me', json={'name':'Anonymous'}).status_code == 401
    assert client.patch('/auth/me', headers=auth, json={'name':'  '}).status_code == 422
    assert client.patch('/auth/me', headers=auth, json={'name':'New name', 'email':'other@example.com'}).status_code == 422
    r = client.patch('/auth/me', headers=auth, json={'name':'Renamed owner'})
    assert r.status_code == 200 and r.json()['email'] == 'owner@example.com'
    assert client.get('/auth/me', headers=auth).json()['name'] == 'Renamed owner'
    assert client.get('/auth/me', headers=other).json()['name'] == 'other'


def test_profile_rename_owner_only(client):
    _, owner = account(client, 'owner@example.com')
    _, caregiver = account(client, 'care@example.com')
    _, other = account(client, 'other@example.com')
    pid = profile(client, owner)
    join(client, owner, caregiver, pid, 'care@example.com', 'caregiver')
    path = f'/profiles/{pid}/name'
    assert client.patch(path, headers=caregiver, json={'name':'Unauthorized'}).status_code == 403
    assert client.patch(path, headers=other, json={'name':'Unauthorized'}).status_code == 404
    assert client.patch(path, headers=owner, json={'name':'  '}).status_code == 422
    assert client.patch(path, headers=owner, json={'name':'New care name'}).json()['name'] == 'New care name'
    assert client.get('/profiles', headers=caregiver).json()[0]['name'] == 'New care name'
    assert client.get('/profiles', headers=owner).json()[0]['timezone'] == 'Asia/Kolkata'
