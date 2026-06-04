import pandas as pd
import smtplib
import os
import time
import random
import json

from datetime import datetime
from dotenv import load_dotenv
from email.message import EmailMessage

load_dotenv()

# =====================================
# MAILBOXES
# =====================================

mailboxes = [

    {
        "name": "Zoho Main",
        "email": os.getenv("ZOHO_EMAIL"),
        "password": os.getenv("ZOHO_PASSWORD"),
        "smtp": "smtp.zoho.com"
    },

    {
        "name": "Infomaniak Main",
        "email": os.getenv("INFO_EMAIL"),
        "password": os.getenv("INFO_PASSWORD"),
        "smtp": "mail.infomaniak.com"
    },

    {
        "name": "UIUX",
        "email": os.getenv("UIUX_EMAIL"),
        "password": os.getenv("UIUX_PASSWORD"),
        "smtp": "smtp.zoho.com"
    },

    {
        "name": "Commercials",
        "email": os.getenv("COMMERCIALS_EMAIL"),
        "password": os.getenv("COMMERCIALS_PASSWORD"),
        "smtp": "smtp.zoho.com"
    },

    {
        "name": "Creative",
        "email": os.getenv("CREATIVE_EMAIL"),
        "password": os.getenv("CREATIVE_PASSWORD"),
        "smtp": "smtp.zoho.com"
    }
]

# =====================================
# SETTINGS
# =====================================

MAX_PER_MAILBOX = 5

COUNTER_FILE = "daily_counts.json"

# =====================================
# LOAD COUNTERS
# =====================================

today = datetime.now().strftime("%Y-%m-%d")

if os.path.exists(COUNTER_FILE):

    with open(COUNTER_FILE, "r") as f:
        data = json.load(f)

    if data["date"] == today:
        mailbox_counts = data["counts"]

    else:
        mailbox_counts = {}

else:
    mailbox_counts = {}

for mailbox in mailboxes:
    mailbox_counts.setdefault(mailbox["name"], 0)

# =====================================
# LOAD LEADS
# =====================================

leads = pd.read_csv("fresh_leads.csv")

if leads.empty:
    print("No fresh leads.")
    exit()

print("\nAurum Studios Outreach Engine Started\n")

sent_emails = []

# =====================================
# SEND LOOP
# =====================================

for index, lead in leads.iterrows():

    mailbox = mailboxes[index % len(mailboxes)]

    if mailbox_counts[mailbox["name"]] >= MAX_PER_MAILBOX:

        print(f"{mailbox['name']} daily limit reached.")
        continue

    try:

        msg = EmailMessage()

        msg["Subject"] = lead["subject_line"]
        msg["From"] = mailbox["email"]
        msg["To"] = lead["email"]

        msg.set_content(lead["full_email"])

        with smtplib.SMTP_SSL(mailbox["smtp"], 465) as smtp:

            smtp.login(
                mailbox["email"],
                mailbox["password"]
            )

            smtp.send_message(msg)

        print(
            f"✓ Sent to {lead['email']} "
            f"using {mailbox['name']}"
        )

        mailbox_counts[mailbox["name"]] += 1

        sent_row = pd.DataFrame([{

            "name": lead["name"],
            "company": lead["company"],
            "email": lead["email"],
            "subject_line": lead["subject_line"],
            "mailbox_used": mailbox["name"],
            "sent_at": datetime.now(),
            "status": "sent"

        }])

        sent_row.to_csv(
            "sent_leads.csv",
            mode="a",
            header=not os.path.exists("sent_leads.csv"),
            index=False
        )

        sent_emails.append(lead["email"])

    except Exception as e:

        print(f"\nFAILED -> {lead['email']}")
        print(e)
        print()

    wait_time = random.randint(45, 90)

    print(f"Waiting {wait_time}s\n")

    time.sleep(wait_time)

# =====================================
# REMOVE SENT LEADS
# =====================================

remaining = leads[
    ~leads["email"].isin(sent_emails)
]

remaining.to_csv(
    "fresh_leads.csv",
    index=False
)

# =====================================
# SAVE COUNTERS
# =====================================

with open(COUNTER_FILE, "w") as f:

    json.dump({

        "date": today,
        "counts": mailbox_counts

    }, f)

print("\nDaily sending completed.")