# Catalyst ElderCare — Connected Care Edition

Cumulative upgrade: includes Phase 1–4, Premium and Advanced Edition plus CareSOS, CareCheck, CarePassport, optional CareLens and an installable PWA shell. The landing page includes a non-blocking animated brand introduction and the workspace has an improved footer, quick actions, a sign-out farewell and reduced-motion support. Existing SQLite/PostgreSQL data is preserved: startup creates three new tables (`emergency_contacts`, `wellness_checks`, `care_shares`). For real-world use, maintain proper migrations and backups.

## Install and deploy

Extract directly into the project root, replace matching files. Do not replace your private `.env` or database. Install dependencies (`python -m pip install -r requirements.txt`), then `python -m pytest -q` (24 tests). Start locally with `python -m uvicorn backend.main:create_from_env --factory --reload`. Commit source files and deploy latest commit on Render. Do not commit `.env`, keys or database files. Keep existing Render secrets. Copy the included `google-integration/Code.gs` into the private Apps Script if you have not yet installed the Advanced Edition script; save and keep the existing trigger and properties. The new features do not require changing the existing email scheduler. For best QR link accuracy set `PUBLIC_APP_URL=https://catalyst-eldercare.onrender.com` to the exact deployed HTTPS origin, no trailing path. This is optional; links generated in the browser use its current origin.

## CareSOS

Get help from the header or CareSOS navigation. The India emergency link opens the phone dialer for 112; outside India use local emergency services. The patient profile owner can save consenting doctor and family contacts in international format (+country code followed by digits). Authorized members can view and open the dialer. Desktop requires a configured telephone handler. The website does not place the call itself, dispatch responders, monitor emergencies, transmit location or guarantee a response. Do NOT call 112 as a demonstration. Show the button, or test a personal consenting number. Automatic Twilio escalation (see ADVANCED_UPGRADE.md) remains optional, non-emergency and independently configured.

## CareCheck

Profile owner records one check-in per local calendar day; can revise it. A need-help response opens a persistent in-app request visible to Care Circle members; acknowledgement does not prove assistance was provided. An existing request is not silently closed by a mood update. Use CareSOS for immediate help. The Command Center displays open requests. These check-ins are self-reports, not clinical assessments; they do not generate separate email or voice notifications in this version.

## CarePassport

Owner explicitly consents to create a revocable 30-minute bearer link and QR code. Only the latest link is active. A recipient can open without account, and sees the profile name, medication schedules and seven-day counts (not account email, contacts, or full timeline). The token is random, stored as a hash server-side, passed in a URL fragment and submitted to an API with no-store. Anyone possessing it can see the summary until expiry/revocation; share only privately. Revoking cannot erase previously viewed or copied information. This is not a validated FHIR export, emergency medical record or clinical credential.

## CareLens (optional Gemini API)

For a fictional prescription image only: get your own key from Google AI Studio if eligible, set `GEMINI_API_KEY` and `GEMINI_MODEL` on Render (choose a currently available image-capable model listed for your account; do not guess a deprecated model). Deploy, then open CareLens, choose a JPEG/PNG under 2 MB and consent. The image is transmitted to Google; do not upload real personal/health data. The service returns a plain text review draft, with instructions to flag uncertainties. Model output is untrusted and can be wrong. No schedules are created automatically; verify manually with a qualified clinician. Without the key/model the feature reports it is unconfigured, not fake results. API terms, availability, quotas and charges may vary. Key stays in Render; never GitHub. Live Gemini service has not been tested; the unit test mocks its response.

## CareAnywhere

The manifest, icons and service worker allow installation where the browser supports it. Settings → Install ElderCare app, or browser menu → Install/Add to Home Screen. Offline fallback caches static public shell only, not patient records, tokens, doctor-share pages or API responses. Requires online connection for account and records; this is not offline medication logging, background push delivery or a native iOS/Android application. No new provider configuration required. Service worker and install behavior need testing on the actual device/browser.

## Verification

24 pytest tests passed, including contacts permissions/validation, daily check-in and acknowledgement, QR share permissions/revocation/expiry, mocked prescription transcription without schedule creation, and PWA shell responses. JavaScript syntax checked with Node. Browser testing in the build environment was blocked by the browser's local-navigation policy; verify visual layout and interactions on your laptop. Local tests use SQLite, not live Render/PostgreSQL. Previous successful email delivery remains verified from the earlier deployment, not re-tested for this upgrade. Actual Twilio calls, live Gemini, PWA installation and the new production deployment still need verification.

This is a hackathon prototype. Use fictional patient records only. Not a medical device, emergency dispatch service or clinical decision-making system. Never rely on it for real emergencies.
