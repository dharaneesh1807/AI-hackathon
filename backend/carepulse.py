"""CarePulse: schedule snapshots, adherence and accountable follow-up.

Unconfirmed is not evidence of a missed dose. Never recommend a replacement dose.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select, update

from .models import CareEvent, Dose, Medication, Profile
from .schemas import Input

GRACE_SECONDS = 30 * 60  # Prototype care-plan default; not clinical guidance.
HORIZON_DAYS = 7


class DoseAction(Input):
    status: Literal['taken', 'skipped', 'help_requested']
    note: str = Field(default='', max_length=500)


class FollowUpAction(Input):
    action: Literal['claim', 'resolve', 'release']
    note: str = Field(default='', max_length=500)


def lock_profile(session, profile_id):
    # PostgreSQL serializes changes within each profile. SQLite is for local development.
    p = session.scalar(select(Profile).where(Profile.id == profile_id).with_for_update())
    if p is None:
        raise HTTPException(404, 'Profile not found')
    return p


def event(session, d, action, now, actor=None, note=''):
    session.add(CareEvent(profile_id=d.profile_id, dose_id=d.id, actor_id=actor,
                          action=action, at=now, note=note))


def change(session, d, now, action, actor=None, note='', **values):
    """Compare-and-swap prevents competing actions silently overwriting each other."""
    result = session.execute(update(Dose).where(Dose.id == d.id, Dose.version == d.version)
                             .values(**values, version=d.version + 1))
    if result.rowcount != 1:
        raise HTTPException(409, 'Dose changed; refresh and try again')
    session.refresh(d)
    event(session, d, action, now, actor, note)


def seed_medication(session, profile, med, now):
    zone = ZoneInfo(profile.timezone)
    start = datetime.fromtimestamp(now, zone).date()
    existing = {d.due_at: d for d in session.scalars(select(Dose).where(
        Dose.profile_id == profile.id, Dose.medication_id == med.id, Dose.due_at >= now))}
    for offset in range(HORIZON_DAYS + 1):
        day = start + timedelta(days=offset)
        for hhmm in med.times.split(','):
            hour, minute = map(int, hhmm.split(':'))
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            due = int(local.timestamp())
            # Nonexistent wall-clock times during DST shift forward; ambiguous times use fold=0.
            if due < now:
                continue
            d = existing.get(due)
            snapshot = dict(medication_name=med.name, dosage=med.dosage, instructions=med.instructions)
            if d is None:
                session.add(Dose(profile_id=profile.id, medication_id=med.id,
                                 due_at=due, **snapshot))
            elif d.status == 'cancelled':
                change(session, d, now, 'schedule_restored', status='scheduled', **snapshot)


def cancel_future(session, med, now):
    for d in session.scalars(select(Dose).where(Dose.profile_id == med.profile_id,
                  Dose.medication_id == med.id, Dose.due_at > now, Dose.status == 'scheduled')):
        change(session, d, now, 'schedule_cancelled', status='cancelled')


def refresh(session, profile, now):
    for med in session.scalars(select(Medication).where(Medication.profile_id == profile.id)):
        seed_medication(session, profile, med, now)
    session.flush()
    count = 0
    for d in session.scalars(select(Dose).where(Dose.profile_id == profile.id,
                Dose.status.in_(['scheduled', 'due']), Dose.due_at <= now)):
        if now >= d.due_at + GRACE_SECONDS:
            change(session, d, now, 'dose_unconfirmed', status='unconfirmed', follow_up='open')
            count += 1
        elif d.status == 'scheduled':
            change(session, d, now, 'dose_due', status='due')
    return count


def record_dose(session, d, data, user_id, role, now):
    if d.status == data.status:
        return  # Safe retry; no duplicate audit event.
    if d.status == 'cancelled' or d.due_at > now:
        raise HTTPException(409, 'Only a due, active dose can be recorded')
    if d.status in ('taken', 'skipped'):
        raise HTTPException(409, 'Dose already recorded; do not record another dose')
    if role == 'caregiver' and not data.note:
        raise HTTPException(422, 'Add a note when reporting on behalf of the patient')
    values = {'status': data.status}
    if data.status == 'taken':
        if d.follow_up in ('open', 'claimed'):
            values['follow_up'] = 'resolved'
    else:
        if d.follow_up in ('none', 'resolved'):
            values.update(follow_up='open', claimed_by=None)
    change(session, d, now, 'dose_' + data.status, user_id, data.note, **values)


def follow_up(session, d, data, user_id, role, now):
    if data.action == 'claim':
        if d.follow_up == 'claimed' and d.claimed_by == user_id:
            return
        if d.follow_up != 'open':
            raise HTTPException(409, 'This follow-up is not open')
        change(session, d, now, 'follow_up_claimed', user_id, data.note,
               follow_up='claimed', claimed_by=user_id)
    elif data.action == 'release':
        if d.follow_up != 'claimed' or (d.claimed_by != user_id and role != 'owner'):
            raise HTTPException(409, 'Only the assigned caregiver or owner can release')
        change(session, d, now, 'follow_up_released', user_id, data.note,
               follow_up='open', claimed_by=None)
    else:
        if d.follow_up == 'resolved' and d.claimed_by == user_id:
            return
        if d.follow_up != 'claimed' or (d.claimed_by != user_id and role != 'owner'):
            raise HTTPException(409, 'Claim the follow-up before resolving it')
        if not data.note:
            raise HTTPException(422, 'Record how the follow-up was resolved')
        # Resolving a follow-up is not proof the medication was taken.
        change(session, d, now, 'follow_up_resolved', user_id, data.note,
               follow_up='resolved')


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def dose_json(d):
    return {'id': d.id, 'medication_id': d.medication_id, 'medication_name': d.medication_name,
            'dosage': d.dosage, 'instructions': d.instructions, 'due_at': iso(d.due_at),
            'status': d.status, 'follow_up': d.follow_up, 'claimed_by': d.claimed_by}


def event_json(e):
    return {'id': e.id, 'dose_id': e.dose_id, 'actor_id': e.actor_id,
            'action': e.action, 'at': iso(e.at), 'note': e.note}
