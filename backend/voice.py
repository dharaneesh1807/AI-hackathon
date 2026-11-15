"""Optional consent-based phone escalation; no medical content or emergency claims."""
import json
import re
from typing import Literal
from sqlalchemy import select
from .models import Dose, Membership, User, VoicePreference, VoiceAttempt
from .schemas import Input

class VoiceResult(Input):
    status: Literal['accepted', 'failed']


def approved_numbers(raw):
    values = json.loads(raw or '{}')
    if not isinstance(values, dict):
        raise ValueError('DEMO_VOICE_RECIPIENTS must be a JSON object')
    result = {}
    for email, number in values.items():
        if not isinstance(number, str) or not re.fullmatch(r'\+[1-9]\d{7,14}', number):
            raise ValueError('Approved phone numbers must be in E.164 format')
        result[email.strip().lower()] = number
    return result


def dispatch(session, pid, now, numbers, threshold, limit):
    if not numbers or limit <= 0:
        return []
    members = session.execute(select(User.id, User.email).join(Membership, User.id == Membership.user_id)
        .join(VoicePreference, (VoicePreference.user_id == User.id) & (VoicePreference.profile_id == Membership.profile_id))
        .where(Membership.profile_id == pid, VoicePreference.enabled.is_(True), User.email.in_(list(numbers)))
        .order_by(User.id)).all()
    if not members:
        return []
    doses = list(session.scalars(select(Dose).where(Dose.profile_id == pid, Dose.status == 'unconfirmed',
        Dose.follow_up == 'open', Dose.due_at <= now-threshold*60, Dose.due_at >= now-24*3600).order_by(Dose.due_at)))
    result = []
    for uid, email in members:
        # At most one request per account per rolling day; never retry uncertain attempts.
        recent = session.scalar(select(VoiceAttempt.id).where(VoiceAttempt.user_id == uid,
            VoiceAttempt.created_at > now-86400).limit(1))
        if recent is not None:
            continue
        for dose in doses:
            seen = session.scalar(select(VoiceAttempt.id).where(VoiceAttempt.profile_id == pid,
                VoiceAttempt.user_id == uid, VoiceAttempt.dose_id == dose.id))
            if seen is not None:
                continue
            attempt = VoiceAttempt(profile_id=pid, user_id=uid, dose_id=dose.id, created_at=now, status='dispatched')
            session.add(attempt)
            session.flush()
            result.append({'id': attempt.id, 'to': numbers[email]})
            break
        if len(result) >= limit:
            break
    return result
