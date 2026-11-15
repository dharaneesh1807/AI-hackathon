# Catalyst ElderCare — Phase 1

A closed-loop elderly-care hackathon prototype. This milestone implements a FastAPI backend for account authentication, secure CareCircles, medication schedules and appointments. It is not a medical device or emergency monitoring system. Use synthetic data only.

## Local setup (Windows PowerShell, in project root)

With your Python virtual environment activated:

```powershell
python -m pip install -r requirements.txt
python -c "import secrets; from pathlib import Path; p=Path('.env'); p.exists() or p.write_text('DATABASE_URL=sqlite:///./eldercare.db\nJWT_SECRET='+secrets.token_urlsafe(48)+'\n', encoding='utf-8')"
python -m pytest -q
python -m uvicorn backend.main:create_from_env --factory --reload
```

Open http://127.0.0.1:8000/docs for Swagger UI. Register, log in, copy `access_token`, then click Authorize and enter the token. Create a profile, then use its returned ID to manage medication and appointments. Owner can invite a specific registered email with a one-time code; the invited user logs in and calls `/care-circle/join`. Owner can revoke membership. Caregivers can edit schedules; family can view only.

The SQLite database and `.env` are ignored by Git. For PostgreSQL use a SQLAlchemy-compatible `DATABASE_URL` and the provider's TLS settings. PostgreSQL has not been tested in this milestone. Do not deploy with a SQLite database on ephemeral hosting. Never publish secrets or actual patient data.

## What remains

- React frontend, accessibility and language support.
- Dose-instance tracking and patient confirmation; reliable escalation, notification deduplication and email delivery.
- Google Apps Script and Calendar integration.
- Verified email ownership, password recovery, stronger distributed rate limiting, audit trail, migrations, production security and monitoring.
- Production deployment and end-to-end verification.

The current registration accepts unverified emails; invitation email binding is not proof of email ownership. This prototype must not be used with real health information. JWTs expire after one hour. Access checks are applied server-side for each profile. The in-process rate limiter is only a development safeguard. Local tests use temporary SQLite databases.

## Phase 2: CarePulse

This update adds two tables (`doses`, `care_events`) without changing the Phase 1 table schemas. Back up your local database before updating. On startup, SQLAlchemy creates the additional tables. Existing accounts, medications and appointments are retained. Existing medication schedules begin generating future doses when the first refresh runs; past doses are not fabricated.

- Daily scheduled doses are snapshotted in UTC using the patient profile's IANA timezone. The engine schedules today through the next seven calendar days; refresh regularly to extend the horizon.
- A dose becomes `due`, then `unconfirmed` after a prototype 30-minute grace period. Unconfirmed means no report was received, not proof that medication was missed.
- Owners can report `taken`, `skipped` or `help_requested`. Caregivers can report on behalf of the patient with a note. Family members can read records and coordinate follow-ups, but cannot mark a dose taken.
- Follow-ups can be claimed, released or resolved. Resolution does not automatically mark the dose taken. The audit timeline records changes and the actor. Repeated confirmation is idempotent, conflicting terminal reports are rejected.
- Medication edits/deletion cancel future scheduled doses while preserving historical snapshots. Caregiver revocation releases outstanding claims.

### CarePulse endpoints

All profile endpoints require the Phase 1 bearer token and appropriate membership.

| Method | Path |
| --- | --- |
| POST | `/profiles/{profile_id}/carepulse/refresh` |
| GET | `/profiles/{profile_id}/carepulse/doses` |
| GET | `/profiles/{profile_id}/carepulse/alerts` |
| POST | `/profiles/{profile_id}/carepulse/doses/{dose_id}/record` |
| POST | `/profiles/{profile_id}/carepulse/doses/{dose_id}/follow-up` |
| GET | `/profiles/{profile_id}/carepulse/timeline` |
| POST | `/internal/carepulse/refresh` |

The internal endpoint is disabled unless a separate `SCHEDULER_SECRET` is configured; provide it as the `X-Scheduler-Token` header. Use a strong random secret, never put it in the public repository. This endpoint processes all profiles and returns aggregate counts only. No external scheduler or email delivery is configured in this phase. To check locally, an owner/caregiver can call the profile refresh endpoint in Swagger; the eventual external scheduler must call the internal endpoint periodically over HTTPS.

Record body: `{"status":"taken"}`. Follow-up body: `{"action":"claim"}` or `{"action":"resolve","note":"Contacted patient; outcome recorded"}`. Use fictional patient data only. This is a prototype, not medical monitoring or emergency response. It does not recommend taking an additional dose, changing medication, or changing clinical instructions.

Tests: `python -m pytest -q` (10 tests: 5 original + 5 CarePulse). The automated tests use SQLite and an injected clock; PostgreSQL concurrency and deployment, email delivery, user-facing accessibility, and clinical readiness are not yet verified. PostgreSQL row locks serialize per-profile modifications; SQLite is intended for local single-instance testing. A prolonged scheduler outage beyond the generation horizon needs an explicit reconciliation process.

## Phase 3 — browser interface

Run `python -m pytest -q` and start the existing server:

```sh
python -m uvicorn backend.main:create_from_env --factory --reload
```

Open http://127.0.0.1:8000/ for the application or `/docs` for API documentation.
No Node.js, npm, external CDN, or frontend build step is needed. The responsive HTML/CSS/JavaScript application is served from FastAPI on the same origin. API routes are unchanged except `/` now serves the website. Authentication tokens are kept in memory; reloading the page requires signing in again. Data remains in the database. All profile authorization is enforced by the backend.

Try registering a fictional account, creating a profile, adding a medication with a future daily time, and refreshing the care status after the scheduled time. Create a second account with a different fictional email, generate an invitation as the owner, and join as the invited account. Use the profile owner's or caregiver's dashboard to add/edit schedules, record actual dose status, and claim/resolve follow-ups. The family role can read records and coordinate follow-ups but cannot edit prescriptions or record adherence. Appointment time input uses the device timezone and display uses the profile timezone. The CarePulse engine uses a seven-day future schedule horizon; the dashboard retrieves up to 500 dose records and 100 timeline records.

Comfort mode includes larger medication controls, simplified navigation, English/Tamil labels for key actions, and browser speech synthesis (voice availability varies). Other screens and some labels remain English. This is not a complete localization or accessibility certification. Automatic scheduler execution, email delivery, Google Calendar synchronization, production database verification and deployment are still pending. Do not use real healthcare data or rely on the prototype for clinical care.
