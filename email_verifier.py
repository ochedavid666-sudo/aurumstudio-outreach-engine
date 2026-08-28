import smtplib

import pandas as pd

from aurum_core import (
    CLEAN_LEADS_FILE,
    DEFAULT_COLUMNS,
    VERIFIED_LEADS_FILE,
    email_domain,
    has_mx_record,
    is_disposable_email,
    is_valid_email_format,
    normalize_email,
    read_csv,
    atomic_write_dataframe,
)

VERIFIED_COLUMNS = DEFAULT_COLUMNS + ["verification_status", "verification_reason"]


def smtp_probe(email):
    domain = email_domain(email)
    if not has_mx_record(domain):
        return False

    # Many providers block SMTP recipient probing. Treat network refusal as risky,
    # not invalid, and only use clear recipient rejection as a negative signal.
    try:
        with smtplib.SMTP(domain, 25, timeout=10) as smtp:
            smtp.helo("aurumstudios.local")
            code, _ = smtp.mail("verify@aurumstudios.local")
            if code >= 500:
                return None
            code, _ = smtp.rcpt(email)
            if code in {250, 251}:
                return True
            if code >= 500:
                return False
    except Exception:
        return None

    return None


def classify_email(email, smtp_check=False):
    email = normalize_email(email)
    domain = email_domain(email)

    if not is_valid_email_format(email):
        return "INVALID", "malformed_email"
    if is_disposable_email(email):
        return "INVALID", "disposable_email"
    if not has_mx_record(domain):
        return "INVALID", "no_mx_or_domain_record"

    if smtp_check:
        smtp_result = smtp_probe(email)
        if smtp_result is True:
            return "VALID", "smtp_accepted"
        if smtp_result is False:
            return "INVALID", "smtp_rejected"
        return "RISKY", "smtp_unavailable"

    return "VALID", "mx_valid"


def verify_leads(input_path=CLEAN_LEADS_FILE, output_path=VERIFIED_LEADS_FILE, smtp_check=False):
    leads = read_csv(input_path, columns=DEFAULT_COLUMNS)
    rows = []

    for _, row in leads.iterrows():
        data = row.to_dict()
        data["email"] = normalize_email(data.get("email", ""))
        status, reason = classify_email(data["email"], smtp_check=smtp_check)
        data["verification_status"] = status
        data["verification_reason"] = reason
        if status == "VALID":
            rows.append(data)

    verified = pd.DataFrame(rows, columns=VERIFIED_COLUMNS)
    atomic_write_dataframe(output_path, verified, VERIFIED_COLUMNS)
    print(f"Verified leads: {len(verified)}.")


if __name__ == "__main__":
    verify_leads()
