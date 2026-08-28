from datetime import datetime, timedelta

import pandas as pd

from aurum_core import (
    DEAD_LEADS_FILE,
    DRY_RUN,
    FAILED_LEADS_FILE,
    WAITING_FOLLOWUP_FILE,
    append_row,
    atomic_write_dataframe,
    file_lock,
    increment_quota,
    load_daily_counts,
    load_mailboxes,
    now_iso,
    quota_available,
    read_csv,
    save_daily_counts,
    send_smtp_message,
    wait_between_sends,
)

MAX_FOLLOWUPS = 3
FOLLOWUP_DELAYS = {
    0: timedelta(hours=48),
    1: timedelta(hours=24),
    2: timedelta(hours=24),
}

WAITING_COLUMNS = [
    "name",
    "company",
    "email",
    "website",
    "subject_line",
    "full_email",
    "mailbox_used",
    "mailbox_email",
    "sent_at",
    "followup_count",
    "last_contacted",
    "status",
]


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return datetime.utcnow()


def due_for_followup(row):
    count = int(row.get("followup_count", 0) or 0)
    if count >= MAX_FOLLOWUPS:
        return False
    last_contacted = parse_time(row.get("last_contacted") or row.get("sent_at"))
    return datetime.utcnow() >= last_contacted + FOLLOWUP_DELAYS[count]


def followup_copy(row, next_count):
    company = row.get("company", "your brand")
    name = row.get("name", "there")

    if next_count == 1:
        body = f"Hi {name},\n\nJust wanted to follow up on my note about {company}.\n\nBest,\nAurum Studios"
    elif next_count == 2:
        body = f"Hi {name},\n\nWorth a quick look, or should I close the loop here?\n\nBest,\nAurum Studios"
    else:
        body = f"Hi {name},\n\nLast note from me. If improving {company}'s visual direction becomes relevant, happy to help.\n\nBest,\nAurum Studios"

    return f"Re: {row.get('subject_line', '')}", body


def mailbox_lookup():
    return {mailbox["name"]: mailbox for mailbox in load_mailboxes()}


def run_followups():
    with file_lock("followup_engine"):
        waiting = read_csv(WAITING_FOLLOWUP_FILE, columns=WAITING_COLUMNS)
        if waiting.empty:
            print("No leads waiting for followup.")
            return

        mailboxes = mailbox_lookup()
        counts = load_daily_counts()
        updated_rows = []
        dead_rows = []

        for _, row in waiting.iterrows():
            data = row.to_dict()
            count = int(data.get("followup_count", 0) or 0)

            if count >= MAX_FOLLOWUPS:
                data["status"] = "dead"
                dead_rows.append(data)
                continue

            if not due_for_followup(data):
                updated_rows.append(data)
                continue

            mailbox = mailboxes.get(data.get("mailbox_used", ""))
            if not mailbox:
                append_row(FAILED_LEADS_FILE, {**data, "failed_at": now_iso(), "error": "mailbox_not_found", "status": "failed"})
                updated_rows.append(data)
                continue

            if not quota_available(counts, mailbox["name"], "followup"):
                updated_rows.append(data)
                continue

            next_count = count + 1
            subject, body = followup_copy(data, next_count)

            try:
                send_smtp_message(data, mailbox, subject=subject, body=body)
                if not DRY_RUN:
                    increment_quota(counts, mailbox["name"], "followup")
                    data["followup_count"] = next_count
                    data["last_contacted"] = now_iso()
                    data["status"] = "waiting_followup"

                print(f"Followup #{next_count} sent to {data.get('email')} from {mailbox['name']}")
                wait_between_sends()

            except Exception as e:
                append_row(FAILED_LEADS_FILE, {**data, "failed_at": now_iso(), "error": str(e), "status": "failed"})
                print(f"FAILED FOLLOWUP -> {data.get('email')}: {e}")
                wait_between_sends()

            if int(data.get("followup_count", 0) or 0) >= MAX_FOLLOWUPS:
                data["status"] = "dead"
                dead_rows.append(data)
            else:
                updated_rows.append(data)

        if not DRY_RUN:
            atomic_write_dataframe(WAITING_FOLLOWUP_FILE, pd.DataFrame(updated_rows), WAITING_COLUMNS)
            if dead_rows:
                existing_dead = read_csv(DEAD_LEADS_FILE)
                dead = pd.concat([existing_dead, pd.DataFrame(dead_rows)], ignore_index=True)
                atomic_write_dataframe(DEAD_LEADS_FILE, dead)
            save_daily_counts(counts)

        print("Followup run completed.")


if __name__ == "__main__":
    run_followups()
