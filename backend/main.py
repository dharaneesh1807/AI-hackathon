"""Catalyst ElderCare API. Phase 2 records follow-ups; email delivery is not yet enabled."""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from threading import Lock

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import Appointment, Base, CareEvent, Dose, Invitation, Medication, Membership, Profile, User
from . import carepulse as cp
from .schemas import AppointmentInput, InviteInput, JoinInput, Login, MedicationInput, ProfileInput, Register

load_dotenv()
password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def create_app(database_url: str, secret: str, clock=time.time, scheduler_secret=None):
    if len(secret) < 32:
        raise RuntimeError('JWT_SECRET must contain at least 32 characters')
    # Render/Postgres providers may use the legacy postgres:// scheme.
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    options = {'connect_args': {'check_same_thread': False}} if database_url.startswith('sqlite') else {'pool_pre_ping': True}
    engine = create_engine(database_url, **options)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
    attempts = defaultdict(deque)
    lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title='Catalyst ElderCare', version='0.2.0', lifespan=lifespan)

    def db():
        with sessions() as session:
            yield session

    def limited(request: Request, category: str):
        # Prototype per-process throttling. Use shared storage for production/multiple workers.
        key = (category, request.client.host if request.client else 'unknown')
        now = time.monotonic()
        with lock:
            if len(attempts) >= 10000 and key not in attempts:
                for old_key in list(attempts):
                    if not attempts[old_key] or attempts[old_key][-1] <= now - 60:
                        del attempts[old_key]
                if len(attempts) >= 10000:
                    raise HTTPException(429, 'Too many requests')
            q = attempts[key]
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= 15:
                raise HTTPException(429, 'Too many attempts; try again in one minute')
            q.append(now)

    def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(db)):
        if not credentials:
            raise HTTPException(401, 'Login required', headers={'WWW-Authenticate': 'Bearer'})
        try:
            claims = jwt.decode(credentials.credentials, secret, algorithms=['HS256'], options={'require': ['exp', 'sub', 'iat']})
            user = session.get(User, int(claims['sub']))
        except (jwt.InvalidTokenError, ValueError, TypeError):
            user = None
        if not user:
            raise HTTPException(401, 'Invalid or expired session')
        return user

    def membership(session, profile_id, user_id, roles=None):
        member = session.scalar(select(Membership).where(Membership.profile_id == profile_id, Membership.user_id == user_id))
        if not member:
            raise HTTPException(404, 'Profile not found')
        if roles and member.role not in roles:
            raise HTTPException(403, 'Insufficient permissions')
        return member

    def item_for(session, model, profile_id, item_id):
        item = session.scalar(select(model).where(model.id == item_id, model.profile_id == profile_id))
        if not item:
            raise HTTPException(404, 'Item not found')
        return item

    def invite_hash(code):
        return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()

    def med_json(m):
        return {'id': m.id, 'name': m.name, 'dosage': m.dosage, 'times': m.times.split(','), 'instructions': m.instructions}

    def appt_json(a):
        return {'id': a.id, 'title': a.title, 'doctor': a.doctor, 'starts_at': a.starts_at, 'location': a.location}

    def profile_json(p, role):
        return {'id': p.id, 'name': p.name, 'timezone': p.timezone, 'role': role}

    @app.get('/')
    def root():
        return {'service': 'Catalyst ElderCare', 'phase': 2, 'docs': '/docs'}

    @app.get('/health')
    def health(session: Session = Depends(db)):
        session.execute(select(1))
        return {'status': 'ok'}

    @app.post('/auth/register', status_code=201)
    def register(data: Register, request: Request, session: Session = Depends(db)):
        limited(request, 'register')
        user = User(name=data.name, email=data.email, password_hash=password_hasher.hash(data.password))
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, 'Account could not be created')
        return {'id': user.id, 'name': user.name, 'email': user.email}

    @app.post('/auth/login')
    def login(data: Login, request: Request, session: Session = Depends(db)):
        limited(request, 'login')
        user = session.scalar(select(User).where(User.email == data.email))
        try:
            valid = password_hasher.verify(user.password_hash if user else dummy_hash, data.password)
        except VerificationError:
            valid = False
        if not user or not valid:
            raise HTTPException(401, 'Invalid email or password')
        now = int(time.time())
        token = jwt.encode({'sub': str(user.id), 'iat': now, 'exp': now + 3600}, secret, algorithm='HS256')
        return {'access_token': token, 'token_type': 'bearer', 'expires_in': 3600}

    @app.get('/auth/me')
    def me(user: User = Depends(current_user)):
        return {'id': user.id, 'email': user.email, 'name': user.name}

    @app.post('/profiles', status_code=201)
    def create_profile(data: ProfileInput, user: User = Depends(current_user), session: Session = Depends(db)):
        p = Profile(**data.model_dump())
        session.add(p)
        session.flush()
        session.add(Membership(profile_id=p.id, user_id=user.id, role='owner'))
        session.commit()
        return profile_json(p, 'owner')

    @app.get('/profiles')
    def profiles(user: User = Depends(current_user), session: Session = Depends(db)):
        rows = session.execute(select(Profile, Membership.role).join(Membership, Membership.profile_id == Profile.id).where(Membership.user_id == user.id).order_by(Profile.id))
        return [profile_json(p, role) for p, role in rows]

    @app.post('/profiles/{profile_id}/invitations', status_code=201)
    def invite(profile_id: int, data: InviteInput, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner'})
        code = secrets.token_urlsafe(16)
        expires = int(time.time()) + 3600
        session.add(Invitation(profile_id=profile_id, email=data.email, role=data.role, code_hash=invite_hash(code), expires_at=expires))
        session.commit()
        return {'code': code, 'expires_in': 3600, 'role': data.role, 'email': data.email}

    @app.post('/care-circle/join')
    def join(data: JoinInput, request: Request, user: User = Depends(current_user), session: Session = Depends(db)):
        limited(request, 'join')
        invitation = session.scalar(select(Invitation).where(Invitation.code_hash == invite_hash(data.code)))
        if not invitation or invitation.used or invitation.expires_at <= int(time.time()) or invitation.email != user.email:
            raise HTTPException(400, 'Invalid or expired invitation')
        if session.scalar(select(Membership).where(Membership.profile_id == invitation.profile_id, Membership.user_id == user.id)):
            raise HTTPException(409, 'Already a member')
        result = session.execute(update(Invitation).where(Invitation.id == invitation.id, Invitation.used.is_(False), Invitation.expires_at > int(time.time())).values(used=True))
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(400, 'Invalid or expired invitation')
        session.add(Membership(profile_id=invitation.profile_id, user_id=user.id, role=invitation.role))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, 'Already a member')
        return {'profile_id': invitation.profile_id, 'role': invitation.role}

    @app.get('/profiles/{profile_id}/members')
    def members(profile_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner'})
        rows = session.execute(select(User.id, User.name, User.email, Membership.role).join(Membership, User.id == Membership.user_id).where(Membership.profile_id == profile_id))
        return [{'user_id': uid, 'name': name, 'email': email, 'role': role} for uid, name, email, role in rows]

    @app.delete('/profiles/{profile_id}/members/{member_id}', status_code=204)
    def revoke(profile_id: int, member_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner'})
        member = membership(session, profile_id, member_id)
        if member.role == 'owner':
            raise HTTPException(400, 'Owner cannot be removed')
        cp.lock_profile(session, profile_id)
        for dose in session.scalars(select(Dose).where(Dose.profile_id == profile_id, Dose.claimed_by == member_id, Dose.follow_up == 'claimed')):
            cp.change(session, dose, int(clock()), 'follow_up_released', user.id, 'Care circle access revoked', follow_up='open', claimed_by=None)
        session.delete(member)
        session.commit()
        return Response(status_code=204)

    @app.get('/profiles/{profile_id}/medications')
    def medications(profile_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id)
        return [med_json(m) for m in session.scalars(select(Medication).where(Medication.profile_id == profile_id).order_by(Medication.id))]

    @app.post('/profiles/{profile_id}/medications', status_code=201)
    def add_med(profile_id: int, data: MedicationInput, user: User = Depends(current_user), session: Session = Depends(db)):
        p = cp.lock_profile(session, profile_id)
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        m = Medication(profile_id=profile_id, **data.model_dump(exclude={'times'}), times=','.join(data.times))
        session.add(m)
        session.flush()
        cp.seed_medication(session, p, m, int(clock()))
        session.commit()
        return med_json(m)

    @app.put('/profiles/{profile_id}/medications/{item_id}')
    def edit_med(profile_id: int, item_id: int, data: MedicationInput, user: User = Depends(current_user), session: Session = Depends(db)):
        p = cp.lock_profile(session, profile_id)
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        m = item_for(session, Medication, profile_id, item_id)
        now = int(clock())
        cp.cancel_future(session, m, now)
        for key, value in data.model_dump(exclude={'times'}).items():
            setattr(m, key, value)
        m.times = ','.join(data.times)
        cp.seed_medication(session, p, m, now)
        session.commit()
        return med_json(m)

    @app.delete('/profiles/{profile_id}/medications/{item_id}', status_code=204)
    def delete_med(profile_id: int, item_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        cp.lock_profile(session, profile_id)
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        m = item_for(session, Medication, profile_id, item_id)
        cp.cancel_future(session, m, int(clock()))
        session.delete(m)
        session.commit()
        return Response(status_code=204)

    @app.get('/profiles/{profile_id}/appointments')
    def appointments(profile_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id)
        return [appt_json(a) for a in session.scalars(select(Appointment).where(Appointment.profile_id == profile_id).order_by(Appointment.starts_at))]

    @app.post('/profiles/{profile_id}/appointments', status_code=201)
    def add_appt(profile_id: int, data: AppointmentInput, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        a = Appointment(profile_id=profile_id, **data.model_dump(exclude={'starts_at'}), starts_at=data.starts_at.isoformat())
        session.add(a)
        session.commit()
        return appt_json(a)

    @app.put('/profiles/{profile_id}/appointments/{item_id}')
    def edit_appt(profile_id: int, item_id: int, data: AppointmentInput, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        a = item_for(session, Appointment, profile_id, item_id)
        for key, value in data.model_dump(exclude={'starts_at'}).items():
            setattr(a, key, value)
        a.starts_at = data.starts_at.isoformat()
        session.commit()
        return appt_json(a)

    @app.delete('/profiles/{profile_id}/appointments/{item_id}', status_code=204)
    def delete_appt(profile_id: int, item_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        session.delete(item_for(session, Appointment, profile_id, item_id))
        session.commit()
        return Response(status_code=204)

    @app.post('/profiles/{profile_id}/carepulse/refresh')
    def refresh_care(profile_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        p = cp.lock_profile(session, profile_id)
        membership(session, profile_id, user.id, {'owner', 'caregiver'})
        count = cp.refresh(session, p, int(clock()))
        session.commit()
        return {'new_unconfirmed': count}

    @app.get('/profiles/{profile_id}/carepulse/doses')
    def list_doses(profile_id: int, limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0), user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id)
        rows = session.scalars(select(Dose).where(Dose.profile_id == profile_id, Dose.status != 'cancelled')
                   .order_by(Dose.due_at.desc(), Dose.id.desc()).offset(offset).limit(limit))
        return [cp.dose_json(d) for d in rows]

    @app.get('/profiles/{profile_id}/carepulse/alerts')
    def alerts(profile_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id)
        rows = session.scalars(select(Dose).where(Dose.profile_id == profile_id, Dose.follow_up.in_(['open', 'claimed']))
                   .order_by(Dose.due_at).limit(500))
        return [cp.dose_json(d) for d in rows]

    @app.post('/profiles/{profile_id}/carepulse/doses/{dose_id}/record')
    def record(profile_id: int, dose_id: int, data: cp.DoseAction, user: User = Depends(current_user), session: Session = Depends(db)):
        cp.lock_profile(session, profile_id)
        member = membership(session, profile_id, user.id, {'owner', 'caregiver'})
        d = item_for(session, Dose, profile_id, dose_id)
        cp.record_dose(session, d, data, user.id, member.role, int(clock()))
        session.commit()
        return cp.dose_json(d)

    @app.post('/profiles/{profile_id}/carepulse/doses/{dose_id}/follow-up')
    def handle_follow_up(profile_id: int, dose_id: int, data: cp.FollowUpAction, user: User = Depends(current_user), session: Session = Depends(db)):
        cp.lock_profile(session, profile_id)
        member = membership(session, profile_id, user.id)
        d = item_for(session, Dose, profile_id, dose_id)
        cp.follow_up(session, d, data, user.id, member.role, int(clock()))
        session.commit()
        return cp.dose_json(d)

    @app.get('/profiles/{profile_id}/carepulse/timeline')
    def timeline(profile_id: int, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 user: User = Depends(current_user), session: Session = Depends(db)):
        membership(session, profile_id, user.id)
        rows = session.scalars(select(CareEvent).where(CareEvent.profile_id == profile_id)
                               .order_by(CareEvent.at.desc(), CareEvent.id.desc()).offset(offset).limit(limit))
        return [cp.event_json(e) for e in rows]

    @app.post('/internal/carepulse/refresh')
    def scheduler_refresh(x_scheduler_token: str | None = Header(default=None), session: Session = Depends(db)):
        if not scheduler_secret or not x_scheduler_token or not hmac.compare_digest(scheduler_secret, x_scheduler_token):
            raise HTTPException(401, 'Invalid scheduler credentials')
        now = int(clock())
        ids = list(session.scalars(select(Profile.id).order_by(Profile.id)))
        count = 0
        for pid in ids:
            p = cp.lock_profile(session, pid)
            count += cp.refresh(session, p, now)
            session.commit()
        return {'profiles_processed': len(ids), 'new_unconfirmed': count}

    return app


def create_from_env():
    return create_app(os.getenv('DATABASE_URL', 'sqlite:///./eldercare.db'), os.environ['JWT_SECRET'], scheduler_secret=os.getenv('SCHEDULER_SECRET'))
