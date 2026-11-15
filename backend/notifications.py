"""Privacy-minimal demo email reminders. One dispatch attempt per event/recipient.

A transport failure after dispatch has uncertain delivery; never silently retry it.
Only administrator-allowlisted, opted-in member addresses receive messages.
"""
from datetime import datetime
from typing import Literal
from sqlalchemy import select
from .models import Appointment, Dose, EmailAttempt, EmailPreference, Membership, User
from .schemas import Input


class Preference(Input):
    enabled: bool


class DeliveryResult(Input):
    status: Literal['sent', 'failed']


TEXT = {
    'upcoming_dose': ('Catalyst ElderCare: upcoming reminder', 'A scheduled care reminder is coming up.'),
    'unconfirmed_dose': ('Catalyst ElderCare: follow-up needed', 'A scheduled care activity has not been confirmed. Check the care workspace; do not assume a dose was missed.'),
    'appointment': ('Catalyst ElderCare: appointment reminder', 'An upcoming appointment is scheduled in your care workspace.'),
}


def dispatch(session, profile_id, now, allowed, limit):
    if not allowed or limit <= 0:
        return []
    recipients = list(session.execute(select(User.id, User.email, Membership.role)
        .join(Membership, User.id == Membership.user_id)
        .join(EmailPreference, (EmailPreference.user_id == User.id) & (EmailPreference.profile_id == Membership.profile_id))
        .where(Membership.profile_id == profile_id, EmailPreference.enabled.is_(True), User.email.in_(allowed))
        .order_by(User.id)))
    if not recipients:
        return []
    events = []
    for d in session.scalars(select(Dose).where(Dose.profile_id == profile_id,
            Dose.status == 'scheduled', Dose.due_at > now, Dose.due_at <= now + 15*60)):
        events.append((f'dose:{d.id}:upcoming', 'upcoming_dose', True))
    for d in session.scalars(select(Dose).where(Dose.profile_id == profile_id,
            Dose.status == 'unconfirmed', Dose.follow_up.in_(['open','claimed']),
            Dose.due_at >= now - 24*3600)):
        events.append((f'dose:{d.id}:unconfirmed', 'unconfirmed_dose', False))
    for a in session.scalars(select(Appointment).where(Appointment.profile_id == profile_id)):
        due = int(datetime.fromisoformat(a.starts_at).timestamp())
        if now < due <= now + 24*3600:
            events.append((f'appointment:{a.id}:{due}', 'appointment', False))
    seen = set(session.execute(select(EmailAttempt.user_id, EmailAttempt.event_key)
                .where(EmailAttempt.profile_id == profile_id)).all())
    messages = []
    for key, kind, owner_only in events:
        for uid, email, role in recipients:
            if (owner_only and role != 'owner') or (uid, key) in seen:
                continue
            row = EmailAttempt(profile_id=profile_id, user_id=uid, event_key=key,
                               kind=kind, status='dispatched', created_at=now)
            session.add(row)
            session.flush()
            subject, body = TEXT[kind]
            messages.append({'id': row.id, 'to': email, 'subject': subject,
                             'body': body + '\n\nSign in to Catalyst ElderCare to review. Prototype only; not emergency monitoring.'})
            seen.add((uid,key))
            if len(messages) >= limit:
                return messages
    return messages
