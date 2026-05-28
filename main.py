import pandas as pd
import smtplib
import os
import time
import random
from datetime import datetime

from dotenv import load_dotenv
from email.message import EmailMessage

# Load environment variables
load_dotenv()

# Mailboxes
mailboxes = [
    {
        "name": "Zoho",
        "email": os.getenv("ZOHO_EMAIL"),
        "password": os.getenv("ZOHO_PASSWORD"),
        "smtp": "smtp.zoho.com"
    },
    {
        "name": "Infomaniak",
        "email": os.getenv("INFO_EMAIL"),
        "password": os.getenv("INFO_PASSWORD"),
        "smtp": "mail.infomaniak.com"
    }
]

# Load fresh leads
leads = pd.read_csv("fresh_leads.csv")

# Daily sending limit
MAX_PER_MAILBOX = 5

# Mailbox counters
mailbox_counts = {
    "Zoho": 0,
    "Infomaniak": 0
}

print("Aurum Studios Outreach Engine Started...\n")

# Loop through leads
for index, lead in leads.iterrows():

    # Rotate mailbox
    mailbox = mailboxes[index % len(mailboxes)]

    # Stop sending if mailbox limit reached
    if mailbox_counts[mailbox["name"]] >= MAX_PER_MAILBOX:
        print(f"{mailbox['name']} reached daily limit.")
        continue

    try:

        # Create email
        msg = EmailMessage()

        msg["Subject"] = lead["subject_line"]
        msg["From"] = mailbox["email"]
        msg["To"] = lead["email"]

        # Email body
        msg.set_content(lead["full_email"])

        # SMTP send
        with smtplib.SMTP_SSL(mailbox["smtp"], 465) as smtp:
            smtp.login(mailbox["email"], mailbox["password"])
            smtp.send_message(msg)

        print(f"Sent to {lead['email']} using {mailbox['name']}")

        # Increase mailbox count
        mailbox_counts[mailbox["name"]] += 1

        # Create sent lead row
        sent_row = pd.DataFrame([{
            "name": lead["name"],
            "company": lead["company"],
            "email": lead["email"],
            "subject_line": lead["subject_line"],
            "mailbox_used": mailbox["name"],
            "sent_at": datetime.now(),
            "status": "sent"
        }])

        # Save to sent_leads.csv
        sent_row.to_csv(
            "sent_leads.csv",
            mode="a",
            header=not os.path.exists("sent_leads.csv") or os.path.getsize("sent_leads.csv") == 0,
            index=False
        )

        # Remove sent lead from fresh_leads.csv
        leads = leads[leads["email"] != lead["email"]]

        leads.to_csv("fresh_leads.csv", index=False)

        print("Lead moved successfully.\n")

    except Exception as e:
        print(f"Failed for {lead['email']}")
        print(e)
        print("\n")

    # Random delay between 1–2 mins
    wait_time = random.randint(60, 120)

    print(f"Waiting {wait_time} seconds...\n")

    time.sleep(wait_time)

print("Daily sending completed.")