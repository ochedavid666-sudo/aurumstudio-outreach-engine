# Aurum OS Outreach Engine

## Current Architecture

The repository started as a single SMTP sender using:

- `fresh_leads.csv`
- `sent_leads.csv`
- `replied_leads.csv`
- `daily_counts.json`
- `.env`

That worked for manual cold outreach, but it had weak validation, hard-coded mailboxes, one shared quota pool, no followup queue, no reply detection, and no durable failure/rejection history.

## New Architecture

The system is now split into small hourly-safe modules:

- `lead_importer.py`: imports Merchant Genius, Apollo, Shopify, or custom CSV files and normalizes fields.
- `lead_scrubber.py`: removes blank rows, malformed emails, duplicate emails, and duplicate domains.
- `email_verifier.py`: validates email format, disposable domains, MX/domain records, and optional SMTP probing.
- `main.py`: sends verified leads, rotates mailboxes evenly, logs sends, and creates followup queue records.
- `followup_engine.py`: sends followups from the same mailbox that sent the first email.
- `reply_detector.py`: checks unread IMAP messages and moves replied leads out of followup.
- `telegram_notifier.py`: sends a Telegram alert when a reply is detected.
- `aurum_core.py`: shared CSV, mailbox, quota, validation, SMTP, and locking utilities.
- `mailboxes.json`: mailbox configuration that can scale to 10, 50, or 100 mailboxes without code changes.

## Data Flow

CSV source exports:

`lead_importer.py`

`fresh_leads.csv`

`lead_scrubber.py`

`clean_leads.csv`

`email_verifier.py`

`verified_leads.csv`

`main.py`

`waiting_followup.csv`

Then:

- reply detected: `replied_leads.csv`
- no reply after followups: `dead_leads.csv`
- send/import/scrub problems: `failed_leads.csv` or `rejected_leads.csv`

## CRM Flow

Lead states are represented by file location:

- Fresh: `fresh_leads.csv`
- Clean: `clean_leads.csv`
- Verified: `verified_leads.csv`
- Waiting followup: `waiting_followup.csv`
- Replied: `replied_leads.csv`
- Dead: `dead_leads.csv`

Each movement preserves email, company, timestamps, status, and mailbox ownership where relevant.

## Followup Logic

Followup schedule:

- Initial email from `main.py`
- Followup #1 after 48 hours
- Followup #2 after 24 more hours
- Followup #3 after 24 more hours
- Then the lead is moved to `dead_leads.csv`

`followup_engine.py` reads `waiting_followup.csv`, checks due times, sends only eligible followups, and updates `followup_count` plus `last_contacted`.

## Mailbox Ownership

The first mailbox owns the lead.

`main.py` stores both `mailbox_used` and `mailbox_email` in `waiting_followup.csv`. `followup_engine.py` uses `mailbox_used` to send every followup from the original mailbox. Followups are never rotated to another inbox.

## Daily Quota Logic

`daily_counts.json` now has a 24-hour `reset_at` timestamp and per-mailbox counters:

- `new_email_count`
- `followup_count`

Each mailbox can send 5 new emails and 5 followups per day by default. Configure with:

- `AURUM_NEW_EMAIL_LIMIT`
- `AURUM_FOLLOWUP_LIMIT`

## Reply Handling

`reply_detector.py` checks unread IMAP messages for every configured mailbox. If a sender matches `waiting_followup.csv`, it:

- appends the lead to `replied_leads.csv`
- removes the lead from `waiting_followup.csv`
- sends a Telegram alert
- prevents duplicate reply records

## Scheduler Safety

The runnable modules use lock files in `.locks/` so Windows Task Scheduler can run them hourly without overlapping the same task:

- `main.py`
- `followup_engine.py`
- `reply_detector.py`

## Problems Found

- Blank CSV rows were treated as real leads.
- Mailboxes were hard-coded in `main.py`.
- Daily quota tracking had one old counter shape and no separate followup pool.
- Sends were not moved into a followup queue.
- Failures were terminal-only and could not be retried intelligently.
- `smtp_test.py` had a hard-coded recipient.
- `replied_leads.csv` had no reliable schema.
- The repository ignores `venv/`, but the virtual environment is already tracked by Git.

## Security Risks

- `.env` stores mailbox credentials; keep it ignored and never commit it.
- Telegram token and chat ID must remain in `.env`.
- SMTP/IMAP exceptions can include provider detail; avoid sharing logs publicly.
- Add unsubscribe and suppression handling before increasing volume.

## Scaling Bottlenecks

- CSV files are acceptable for Phase 1, but concurrent multi-machine execution needs SQLite or Postgres.
- SMTP sends are synchronous and intentionally slow for deliverability.
- IMAP reply detection is provider-dependent and should eventually track message IDs.
- Email verification without a paid verification API will be conservative and sometimes classify catch-all domains imperfectly.

## Deliverability Recommendations

- Keep new-email and followup quotas low while warming inboxes.
- Use separate tracking for bounces, unsubscribes, and spam complaints.
- Add SPF, DKIM, and DMARC checks to mailbox onboarding.
- Avoid SMTP recipient probing at scale; many providers dislike it.
- Personalize copy and avoid sending the same body repeatedly.

## WhatsApp Future Evaluation

Do not implement WhatsApp yet.

For future alerts, WhatsApp Cloud API is better if Aurum wants direct Meta ownership, lower vendor lock-in, and internal engineering control. Twilio WhatsApp is better if Aurum wants faster setup, simpler templates, and paid support. For this system, Telegram is the right Phase 1 alert channel because it is simpler and has fewer approval steps.

## Roadmap

1. Add `suppression_list.csv` for unsubscribes, bounces, and do-not-contact records.
2. Add bounce detection.
3. Move CSV state to SQLite.
4. Add campaign IDs and template versions.
5. Add mailbox health scoring.
6. Add dashboard reporting.
