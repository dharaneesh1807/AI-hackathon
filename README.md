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

## Phase 4 — Google email reminders and calendar handoff

This upgrade adds `email_preferences` and `email_attempts` tables on startup, preserving existing records. It includes a private Google Apps Script scheduler (`google-integration/Code.gs`) that polls over HTTPS every five minutes, refreshes CarePulse, sends privacy-minimal reminders using Google MailApp and reports results. No Google Cloud Run or billing setup is needed for this script in a personal Google account, subject to Apps Script quotas and account restrictions. The script must be installed and authorized by the operator. The backend does not send email by itself.

### Reminder behavior

- Upcoming scheduled dose: within 15 minutes, to opted-in profile owner.
- Unconfirmed dose: after CarePulse grace period, to opted-in members with an open or claimed follow-up (within the previous 24 hours). Unconfirmed is not proof of a missed dose.
- Appointment: within 24 hours, to opted-in members. A rescheduled appointment can produce a new reminder.
- Each event/recipient has a unique database attempt. Repeated polls do not resend it. `sent` means MailApp reported success, not that the recipient read or received it. `failed` or `dispatched` without acknowledgment means delivery failed or is uncertain; this prototype intentionally does not retry ambiguous attempts to avoid duplicate notifications. Check the UI and Apps Script execution logs. A scheduler outage can miss a reminder window. No health information, medication names, patient names or dosages are included in emails.
- Public registration does not verify email ownership. To prevent sending mail to arbitrary addresses, the deployment administrator must allowlist only inboxes they control or whose owners consent to the demo. Each logged-in member also must opt in from **Care Circle → Email reminder settings**. Never use real patient data. Revoking access removes the preference. Messages already dispatched cannot be recalled.

### Deploy the website first (Render)

Create a persistent PostgreSQL database (e.g. a managed provider). Use its SQLAlchemy-compatible connection string in Render, including TLS as required by the provider. Create a Render Web Service from the public GitHub repo, runtime Python, build `pip install -r requirements.txt`, start `python -m uvicorn backend.main:create_from_env --factory --host 0.0.0.0 --port $PORT`, health check `/health`. The included `render.yaml` is an optional blueprint. Supply environment variables through Render's dashboard, never in Git:

- `DATABASE_URL`: managed PostgreSQL connection string; do not use local SQLite in Render.
- `JWT_SECRET`: unique random secret of 32+ characters.
- `SCHEDULER_SECRET`: separate random 32+ character secret (same value in Apps Script).
- `DEMO_EMAIL_ALLOWLIST`: comma-separated consenting test inbox addresses; no spaces required.

To generate a secret locally: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Run twice for distinct values; do not send screenshots containing them. Verify the deployed homepage, `/health`, and a fictional account before configuring reminders. PostgreSQL and hosted service operation still need verification on your own deployment.

### Install the private Google scheduler

1. Visit https://script.google.com/ and create a new project. Copy `google-integration/Code.gs` into its editor. No need to deploy it as a web app.
2. In Project Settings → Script properties add `APP_URL` (your Render HTTPS URL without a trailing slash) and `SCHEDULER_SECRET` (exactly the Render value). Keep the script private.
3. In the deployed site, register using a test inbox from the allowlist, create a fictional profile, and enable Email reminders in Care Circle. Add an appointment scheduled within the next 24 hours and a dose 5–15 minutes in the future.
4. Select `runCareReminders` and click Run. Authorize the script to make external requests and send mail from your Google account. Check the inbox and the recent delivery attempts in Care Circle. Select `installTrigger` and Run once to install the five-minute repeating trigger.
5. Confirm a second run does not send duplicate reminders. For the unconfirmed scenario, leave the fictional dose unconfirmed until after the 30-minute grace period and run again. Check Apps Script Executions for failures. Delete the trigger after the competition if it is no longer needed.

The script uses MailApp quotas and checks remaining quota before dispatch. Render free-tier cold starts and trigger timing are not guaranteed; this is a demonstration, not emergency or clinical monitoring.

### Google Calendar

Appointments have an **Add to Google Calendar** link with a generic title, UTC start time and suggested 30-minute duration. The user reviews and saves the event manually in their own calendar. No patient or doctor names are sent in the link. This is a calendar handoff, not OAuth synchronization; edits/deletion in ElderCare do not change a saved Calendar event. Appointment email reminders are independently handled by MailApp.

### Verification

`python -m pytest -q` — 13 tests (11 previous + 2 notification tests). The new tests verify scheduler authentication, opt-in, allowlist, cross-profile isolation, duplicate prevention, privacy-minimal content, acknowledgment, appointment reminders and revocation. JavaScript syntax checked with Node. Live Google authorization, actual email delivery, browser flows and Render/PostgreSQL deployment are not verified by these tests.
