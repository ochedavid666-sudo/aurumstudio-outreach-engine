import smtplib
import os
from dotenv import load_dotenv
from email.message import EmailMessage

load_dotenv()

msg = EmailMessage()

msg["Subject"] = "SMTP Test"
msg["From"] = os.getenv("UIUX_EMAIL")
msg["To"] = "ochedavid666@gmail.com"

msg.set_content("If you received this, SMTP works.")

try:
    with smtplib.SMTP_SSL("smtp.zoho.com", 465) as smtp:
        smtp.login(
            os.getenv("UIUX_EMAIL"),
            os.getenv("UIUX_PASSWORD")
        )

        smtp.send_message(msg)

    print("SUCCESS")

except Exception as e:
    print("FAILED")
    print(e)