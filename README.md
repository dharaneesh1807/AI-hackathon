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
