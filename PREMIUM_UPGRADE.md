# Catalyst ElderCare — Premium Edition

Extract these six replacement/new source files into the existing project root. Existing `.env`, database, README, deployment configuration and the other tests remain untouched. No new packages or migrations are necessary. The explicit PostgreSQL psycopg2 driver fix is retained.

1. Run `python -m pytest -q` (15 tests expected).
2. Run `python -m uvicorn backend.main:create_from_env --factory --reload` and visit `http://127.0.0.1:8000`. Sign in, open Settings, change your display name and (if owner) your care profile name. Check Today for the seven-day confirmation chart. Check mobile and Elder view. Use only synthetic data.
3. Stage the listed source files, commit and push. Render auto-deploys; verify the live URL and Settings again. Do not edit environment variables.
4. Separately open the existing private Google Apps Script project, replace its `Code.gs` with the included file, and save. Existing script properties and repeating trigger remain in place. Run `runCareReminders` for a newly eligible demo appointment or dose. Check the receiving inbox, including Spam. Previously dispatched reminders are not resent.

## Features and boundaries
- Settings: authenticated display-name updates; owner-only care-profile rename. Sign-in email remains unchanged. Timezone changes are intentionally excluded to avoid altering existing schedule semantics. Language and Elder view use the existing session controls.
- Dashboard: responsive styling, real confirmation counts for the last seven calendar days from up to 500 loaded dose records. No artificial metrics.
- Emails: HTML and plain-text alternatives, branded sender display name, clear CTA, escaped dynamic text, no patient or medicine names. Delivery and spam placement are not guaranteed; validate a new live message.
- Security: name update rejects extra fields and unauthorized users; no database schema changes. Existing prototype limitations remain, including unverified email ownership and no emergency-monitoring guarantee.

Verification performed: 15 pytest tests passed using SQLite; JavaScript syntax checks passed for both scripts; three HTML template assertions passed. Local browser navigation was blocked by the test environment, so visual/browser verification and deployed PostgreSQL name edits need confirmation on your device. No remote deployment or Apps Script changes have been made by the author.
