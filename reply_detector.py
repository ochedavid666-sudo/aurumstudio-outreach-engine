import email
import imaplib
from email.header import decode_header
from email.utils import parseaddr

import pandas as pd

from aurum_core import (
    REPLIED_LEADS_FILE,
    WAITING_FOLLOWUP_FILE,
    atomic_write_dataframe,
    file_lock,
    load_mailboxes,
    normalize_email,
    now_iso,
    read_csv,
    remove_emails,
)
from telegram_notifier import notify_new_reply

REPLIED_COLUMNS = [
    "name",
    "company",
    "email",
    "mailbox",
    "subject",
    "reply_timestamp",
    "status",
]


def decode_subject(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def unread_messages(mailbox):
    imap_host = mailbox.get("imap")
    if not imap_host:
        return []

    messages = []
    with imaplib.IMAP4_SSL(imap_host, int(mailbox.get("imap_port", 993))) as imap:
        imap.login(mailbox["email"], mailbox["password"])
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for message_id in data[0].split():
            _, raw = imap.fetch(message_id, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            sender = normalize_email(parseaddr(msg.get("From", ""))[1])
            messages.append(
                {
                    "sender": sender,
                    "subject": decode_subject(msg.get("Subject", "")),
                    "mailbox": mailbox["name"],
                    "message_id": message_id,
                }
            )
    return messages


def detect_replies():
    with file_lock("reply_detector"):
        waiting = read_csv(WAITING_FOLLOWUP_FILE)
        if waiting.empty:
            print("No leads waiting for followup.")
            return

        replied = read_csv(REPLIED_LEADS_FILE, columns=REPLIED_COLUMNS)
        already_replied = set(replied["email"].map(normalize_email)) if "email" in replied.columns else set()
        waiting_by_email = {
            normalize_email(row["email"]): row.to_dict()
            for _, row in waiting.iterrows()
            if normalize_email(row.get("email", ""))
        }

        new_replies = []
        for mailbox in load_mailboxes():
            try:
                messages = unread_messages(mailbox)
            except Exception as e:
                print(f"Reply check failed for {mailbox['name']}: {e}")
                continue

            for message in messages:
                sender = message["sender"]
                if sender not in waiting_by_email or sender in already_replied:
                    continue

                lead = waiting_by_email[sender]
                row = {
                    "name": lead.get("name", ""),
                    "company": lead.get("company", ""),
                    "email": sender,
                    "mailbox": message["mailbox"],
                    "subject": message["subject"],
                    "reply_timestamp": now_iso(),
                    "status": "replied",
                }
                new_replies.append(row)
                already_replied.add(sender)
                notify_new_reply(
                    row["company"],
                    row["email"],
                    row["mailbox"],
                    row["subject"],
                    row["reply_timestamp"],
                )

        if not new_replies:
            print("No new replies found.")
            return

        updated_replied = pd.concat([replied, pd.DataFrame(new_replies)], ignore_index=True)
        atomic_write_dataframe(REPLIED_LEADS_FILE, updated_replied, REPLIED_COLUMNS)
        atomic_write_dataframe(
            WAITING_FOLLOWUP_FILE,
            remove_emails(waiting, [row["email"] for row in new_replies]),
        )
        print(f"Detected {len(new_replies)} new replies.")


if __name__ == "__main__":
    detect_replies()
