import json
import os
import urllib.parse
import urllib.request

from aurum_core import DRY_RUN


def send_telegram_message(text):
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("Telegram is not configured. Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.")
        return False

    if DRY_RUN:
        print(f"DRY RUN TELEGRAM:\n{text}")
        return True

    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
        return bool(body.get("ok"))


def notify_new_reply(company, email, mailbox, subject, timestamp):
    message = (
        "NEW REPLY\n\n"
        f"Company: {company}\n"
        f"Email: {email}\n"
        f"Mailbox: {mailbox}\n"
        f"Subject: {subject}\n"
        f"Time: {timestamp}"
    )
    return send_telegram_message(message)
