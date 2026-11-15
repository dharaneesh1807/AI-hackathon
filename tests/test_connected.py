from datetime import datetime, timezone
import base64
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from test_api import account, profile, join

@pytest.fixture
def connected(tmp_path):
    now=[int(datetime(2026,11,15,8,tzinfo=timezone.utc).timestamp())]
    app=create_app(f'sqlite:///{tmp_path / "connected.db"}', 'test-secret-'+'x'*40,clock=lambda:now[0])
    with TestClient(app) as c:
        _,owner=account(c,'owner@example.com')
        _,family=account(c,'family@example.com')
        _,outsider=account(c,'outsider@example.com')
        pid=profile(c,owner)
        join(c,owner,family,pid,'family@example.com','family')
        yield c,now,owner,family,outsider,pid

def test_contacts_permissions_and_validation(connected):
    c,_,owner,family,outsider,pid=connected
    path=f'/profiles/{pid}/emergency-contacts'
    assert c.get(path,headers=outsider).status_code==404
    assert c.put(path,headers=family,json={'doctor_phone':'+12025550123'}).status_code==403
    assert c.put(path,headers=owner,json={'doctor_phone':'javascript:bad'}).status_code==422
    assert c.put(path,headers=owner,json={'doctor_name':'Demo doctor','doctor_phone':'+12025550123'}).status_code==200
    assert c.get(path,headers=family).json()['doctor_phone']=='+12025550123'

def test_checkin_daily_and_help_ack(connected):
    c,now,owner,family,outsider,pid=connected
    path=f'/profiles/{pid}/wellness'
    body={'mood':'need_help','sleep':'not_well','water':'not_reported'}
    assert c.post(path,headers=family,json=body).status_code==403
    row=c.post(path,headers=owner,json=body).json()
    assert row['help_status']=='open'
    assert c.post(path,headers=owner,json={**body,'mood':'okay'}).json()['help_status']=='open'
    assert len(c.get(path,headers=family).json())==1
    assert c.post(path+f'/{row["id"]}/acknowledge',headers=outsider).status_code==404
    assert c.post(path+f'/{row["id"]}/acknowledge',headers=family).json()['help_status']=='acknowledged'
    now[0]+=86400
    assert c.post(path,headers=owner,json=body).json()['id']!=row['id']

def test_private_share_expiry_revocation(connected):
    c,now,owner,family,outsider,pid=connected
    path=f'/profiles/{pid}/care-share'
    assert c.post(path,headers=family,json={'consent':True}).status_code==403
    assert c.post(path,headers=owner,json={'consent':False}).status_code==422
    assert c.post(f'/profiles/{pid}/medications',headers=owner,json={'name':'Demo','dosage':'As prescribed','times':['08:00']}).status_code==201
    a=c.post(path,headers=owner,json={'consent':True}).json()
    assert a['qr'].startswith('data:image/svg+xml;base64,')
    assert b'<svg' in base64.b64decode(a['qr'].split(',')[1])
    public='/public/care-share'
    result=c.post(public,json={'token':a['token']})
    assert result.status_code==200 and result.json()['medications'][0]['name']=='Demo'
    assert 'email' not in result.json() and result.headers['cache-control']=='no-store'
    b=c.post(path,headers=owner,json={'consent':True}).json()
    assert c.post(public,json={'token':a['token']}).status_code==404
    assert c.delete(path,headers=owner).status_code==200
    assert c.post(public,json={'token':b['token']}).status_code==404
    d=c.post(path,headers=owner,json={'consent':True}).json()
    now[0]+=1800
    assert c.post(public,json={'token':d['token']}).status_code==404

def test_scan_config_permission_and_no_schedule(connected,monkeypatch):
    c,_,owner,family,outsider,pid=connected
    path=f'/profiles/{pid}/prescription-scan'
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    body={'consent':True,'mime':'image/png','image':'a'*20}
    assert c.post(path,headers=outsider,json=body).status_code==404
    assert c.post(path,headers=family,json=body).status_code==403
    assert c.post(path,headers=owner,json=body).status_code==503
    monkeypatch.setenv('GEMINI_API_KEY','test-key');monkeypatch.setenv('GEMINI_MODEL','test-model')
    assert c.post(path,headers=owner,json=body).status_code==422
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'candidates':[{'content':{'parts':[{'text':'Demo medicine [UNCLEAR]'}]}}]}
    monkeypatch.setattr('backend.connected.httpx.post',lambda *a,**k:Response())
    body['image']=base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'fictional-test').decode()
    assert c.post(path,headers=owner,json=body).json()['draft']=='Demo medicine [UNCLEAR]'
    assert c.get(f'/profiles/{pid}/medications',headers=owner).json()==[]

def test_mobile_shell_and_public_page(connected):
    c,*_=connected
    assert 'manifest.webmanifest' in c.get('/').text
    assert c.get('/doctor-share').headers['cache-control']=='no-store'
    assert c.get('/sw.js').status_code==200
    manifest=c.get('/assets/manifest.webmanifest').json()
    assert manifest['display']=='standalone'
    for icon in manifest['icons']: assert c.get(icon['src']).status_code==200
    assert 'tel:112' in c.get('/assets/offline.html').text
