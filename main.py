from aurum_core import (
    DEFAULT_COLUMNS,
    DRY_RUN,
    FAILED_LEADS_FILE,
    FRESH_LEADS_FILE,
    SENT_LEADS_FILE,
    VERIFIED_LEADS_FILE,
    WAITING_FOLLOWUP_FILE,
    append_row,
    atomic_write_dataframe,
    file_lock,
    increment_quota,
    is_valid_email_format,
    load_daily_counts,
    load_mailboxes,
    now_iso,
    quota_available,
    read_csv,
    remove_emails,
    save_daily_counts,
    send_smtp_message,
    wait_between_sends,
)

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

SENT_COLUMNS = [
    "name",
    "company",
    "email",
    "subject_line",
    "mailbox_used",
    "sent_at",
    "status",
]

FAILED_COLUMNS = [
    "name",
    "company",
    "email",
    "subject_line",
    "mailbox_used",
    "failed_at",
    "error",
    "status",
]


def lead_source_file():
    if VERIFIED_LEADS_FILE.exists() and VERIFIED_LEADS_FILE.stat().st_size > 0:
        return VERIFIED_LEADS_FILE
    print("verified_leads.csv not found. Falling back to fresh_leads.csv.")
    return FRESH_LEADS_FILE


def load_sendable_leads(path):
    leads = read_csv(path, columns=DEFAULT_COLUMNS)
    if leads.empty:
        return leads

    for column in DEFAULT_COLUMNS:
        if column not in leads.columns:
            leads[column] = ""
        leads[column] = leads[column].astype(str).str.strip()

    if "verification_status" in leads.columns:
        leads = leads[leads["verification_status"].str.upper() == "VALID"]

    return leads[
        (leads["email"].map(is_valid_email_format))
        & (leads["subject_line"] != "")
        & (leads["full_email"] != "")
    ]


def next_mailbox(mailboxes, counts, start_index):
    for offset in range(len(mailboxes)):
        mailbox = mailboxes[(start_index + offset) % len(mailboxes)]
        if quota_available(counts, mailbox["name"], "new"):
            return mailbox
    return None


def waiting_row(lead, mailbox):
    return {
        "name": lead.get("name", ""),
        "company": lead.get("company", ""),
        "email": lead.get("email", ""),
        "website": lead.get("website", ""),
        "subject_line": lead.get("subject_line", ""),
        "full_email": lead.get("full_email", ""),
        "mailbox_used": mailbox["name"],
        "mailbox_email": mailbox["email"],
        "sent_at": now_iso(),
        "followup_count": 0,
        "last_contacted": now_iso(),
        "status": "waiting_followup",
    }


def main():
    with file_lock("main"):
        source_file = lead_source_file()
        mailboxes = load_mailboxes()
        counts = load_daily_counts()
        leads = load_sendable_leads(source_file)

        if not mailboxes:
            print("No configured mailboxes.")
            return

        if leads.empty:
            print("No verified leads ready to send.")
            return

        sent_emails = []
        mailbox_pointer = 0

        print("\nAurum OS Outreach Engine Started\n")

        for _, row in leads.iterrows():
            lead = row.to_dict()
            mailbox = next_mailbox(mailboxes, counts, mailbox_pointer)

            if mailbox is None:
                print("All new-email mailbox quotas reached.")
                break

            try:
                send_smtp_message(lead, mailbox)
                mailbox_pointer = (mailboxes.index(mailbox) + 1) % len(mailboxes)

                if not DRY_RUN:
                    increment_quota(counts, mailbox["name"], "new")
                    append_row(
                        SENT_LEADS_FILE,
                        {
                            "name": lead.get("name", ""),
                            "company": lead.get("company", ""),
                            "email": lead.get("email", ""),
                            "subject_line": lead.get("subject_line", ""),
                            "mailbox_used": mailbox["name"],
                            "sent_at": now_iso(),
                            "status": "sent",
                        },
                        SENT_COLUMNS,
                    )
                    append_row(
                        WAITING_FOLLOWUP_FILE,
                        waiting_row(lead, mailbox),
                        WAITING_COLUMNS,
                    )
                    sent_emails.append(lead.get("email", ""))

                print(f"Sent to {lead.get('email')} using {mailbox['name']}")
                wait_between_sends()

            except Exception as e:
                if not DRY_RUN:
                    append_row(
                        FAILED_LEADS_FILE,
                        {
                            "name": lead.get("name", ""),
                            "company": lead.get("company", ""),
                            "email": lead.get("email", ""),
                            "subject_line": lead.get("subject_line", ""),
                            "mailbox_used": mailbox["name"],
                            "failed_at": now_iso(),
                            "error": str(e),
                            "status": "failed",
                        },
                        FAILED_COLUMNS,
                    )
                print(f"FAILED -> {lead.get('email')}: {e}")
                wait_between_sends()

        if not DRY_RUN:
            original = read_csv(source_file)
            remaining = remove_emails(original, sent_emails)
            atomic_write_dataframe(source_file, remaining)
            save_daily_counts(counts)

        print("\nDaily sending completed.")


if __name__ == "__main__":
    main()
