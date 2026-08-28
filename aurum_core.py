import csv
import json
import os
import re
import smtplib
import socket
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

FRESH_LEADS_FILE = BASE_DIR / "fresh_leads.csv"
CLEAN_LEADS_FILE = BASE_DIR / "clean_leads.csv"
VERIFIED_LEADS_FILE = BASE_DIR / "verified_leads.csv"
SENT_LEADS_FILE = BASE_DIR / "sent_leads.csv"
WAITING_FOLLOWUP_FILE = BASE_DIR / "waiting_followup.csv"
REPLIED_LEADS_FILE = BASE_DIR / "replied_leads.csv"
DEAD_LEADS_FILE = BASE_DIR / "dead_leads.csv"
FAILED_LEADS_FILE = BASE_DIR / "failed_leads.csv"
REJECTED_LEADS_FILE = BASE_DIR / "rejected_leads.csv"
DAILY_COUNTS_FILE = BASE_DIR / "daily_counts.json"
MAILBOXES_FILE = BASE_DIR / "mailboxes.json"
LOCK_DIR = BASE_DIR / ".locks"

NEW_EMAIL_LIMIT = int(os.getenv("AURUM_NEW_EMAIL_LIMIT", os.getenv("AURUM_MAX_PER_MAILBOX", "5")))
FOLLOWUP_LIMIT = int(os.getenv("AURUM_FOLLOWUP_LIMIT", "5"))
MIN_WAIT_SECONDS = int(os.getenv("AURUM_MIN_WAIT_SECONDS", "45"))
MAX_WAIT_SECONDS = int(os.getenv("AURUM_MAX_WAIT_SECONDS", "90"))
SMTP_PORT = int(os.getenv("AURUM_SMTP_PORT", "465"))
SMTP_TIMEOUT_SECONDS = int(os.getenv("AURUM_SMTP_TIMEOUT_SECONDS", "30"))
DRY_RUN = os.getenv("AURUM_DRY_RUN", "").lower() in {"1", "true", "yes"}

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
DEFAULT_COLUMNS = ["name", "company", "email", "website", "subject_line", "full_email"]
DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "guerrillamail.com",
    "mailinator.com",
    "tempmail.com",
    "temp-mail.org",
    "yopmail.com",
}


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def now_iso():
    return utc_now().isoformat() + "Z"


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=path.parent,
    ) as tmp:
        tmp.write(text)
        temp_name = tmp.name

    Path(temp_name).replace(path)


def atomic_write_dataframe(path, dataframe, columns=None):
    path = Path(path)
    if columns:
        dataframe = dataframe.reindex(columns=columns)
    atomic_write_text(path, dataframe.to_csv(index=False))


def read_csv(path, columns=None):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])
    return pd.read_csv(path, dtype=str).fillna("")


def append_row(path, row, columns=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = columns or list(row.keys())
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def normalize_email(value):
    return str(value or "").strip().lower()


def email_domain(email):
    email = normalize_email(email)
    return email.rsplit("@", 1)[1] if "@" in email else ""


def is_valid_email_format(email):
    return bool(EMAIL_RE.match(normalize_email(email)))


def is_disposable_email(email):
    return email_domain(email) in DISPOSABLE_DOMAINS


def has_domain_record(domain):
    if not domain:
        return False
    try:
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror:
        return False


def has_mx_record(domain):
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
        return bool(answers)
    except ImportError:
        return has_domain_record(domain)
    except Exception:
        return False


def load_mailboxes():
    if not MAILBOXES_FILE.exists():
        raise FileNotFoundError("mailboxes.json was not found.")

    with MAILBOXES_FILE.open("r", encoding="utf-8") as f:
        raw_mailboxes = json.load(f)

    mailboxes = []
    for mailbox in raw_mailboxes:
        email_env = mailbox.get("email_env", "")
        email = os.getenv(email_env) if email_env else mailbox.get("email", "")
        password_env = mailbox.get("password_env", "")
        password = os.getenv(password_env) if password_env else ""
        if not mailbox.get("name") or not email or not mailbox.get("smtp"):
            print("Skipping mailbox with missing name, email, or smtp.")
            continue
        if not password:
            print(f"Skipping {mailbox['name']}: missing password env {password_env}.")
            continue
        mailboxes.append({**mailbox, "email": email, "password": password})

    return mailboxes


def mailbox_by_name(name):
    for mailbox in load_mailboxes():
        if mailbox["name"] == name:
            return mailbox
    return None


def load_daily_counts():
    if not DAILY_COUNTS_FILE.exists():
        return {"reset_at": (utc_now() + timedelta(hours=24)).isoformat() + "Z", "mailboxes": {}}

    try:
        with DAILY_COUNTS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}

    reset_at = str(data.get("reset_at", ""))
    try:
        reset_time = datetime.fromisoformat(reset_at.replace("Z", ""))
    except ValueError:
        reset_time = utc_now()

    if utc_now() >= reset_time:
        return {"reset_at": (utc_now() + timedelta(hours=24)).isoformat() + "Z", "mailboxes": {}}

    if "mailboxes" not in data or not isinstance(data["mailboxes"], dict):
        data["mailboxes"] = {}
    return data


def save_daily_counts(counts):
    atomic_write_text(DAILY_COUNTS_FILE, json.dumps(counts, indent=2))


def ensure_mailbox_count(counts, mailbox_name):
    mailbox_counts = counts.setdefault("mailboxes", {}).setdefault(
        mailbox_name,
        {"new_email_count": 0, "followup_count": 0},
    )
    mailbox_counts.setdefault("new_email_count", 0)
    mailbox_counts.setdefault("followup_count", 0)
    return mailbox_counts


def quota_available(counts, mailbox_name, quota_type):
    mailbox_counts = ensure_mailbox_count(counts, mailbox_name)
    if quota_type == "followup":
        return int(mailbox_counts["followup_count"]) < FOLLOWUP_LIMIT
    return int(mailbox_counts["new_email_count"]) < NEW_EMAIL_LIMIT


def increment_quota(counts, mailbox_name, quota_type):
    mailbox_counts = ensure_mailbox_count(counts, mailbox_name)
    key = "followup_count" if quota_type == "followup" else "new_email_count"
    mailbox_counts[key] = int(mailbox_counts.get(key, 0)) + 1


def build_message(lead, mailbox, subject=None, body=None):
    msg = EmailMessage()
    msg["Subject"] = subject or lead.get("subject_line", "")
    msg["From"] = mailbox["email"]
    msg["To"] = lead.get("email", "")
    msg.set_content(body or lead.get("full_email", ""))
    return msg


def send_smtp_message(lead, mailbox, subject=None, body=None):
    msg = build_message(lead, mailbox, subject=subject, body=body)

    if DRY_RUN:
        print(f"DRY RUN -> {lead.get('email')} using {mailbox['name']}")
        return

    with smtplib.SMTP_SSL(
        mailbox["smtp"],
        int(mailbox.get("smtp_port", SMTP_PORT)),
        timeout=SMTP_TIMEOUT_SECONDS,
    ) as smtp:
        smtp.login(mailbox["email"], mailbox["password"])
        smtp.send_message(msg)


def wait_between_sends():
    if DRY_RUN:
        return
    time.sleep(__import__("random").randint(MIN_WAIT_SECONDS, MAX_WAIT_SECONDS))


@contextmanager
def file_lock(name, stale_after_seconds=3600):
    LOCK_DIR.mkdir(exist_ok=True)
    lock_path = LOCK_DIR / f"{name}.lock"
    now = time.time()

    if lock_path.exists():
        age = now - lock_path.stat().st_mtime
        if age < stale_after_seconds:
            raise RuntimeError(f"{name} is already running.")
        lock_path.unlink()

    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        if lock_path.exists():
            lock_path.unlink()


def remove_emails(dataframe, emails):
    normalized = {normalize_email(email) for email in emails}
    if "email" not in dataframe.columns:
        return dataframe
    return dataframe[~dataframe["email"].map(normalize_email).isin(normalized)]
