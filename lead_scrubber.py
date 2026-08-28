import pandas as pd

from aurum_core import (
    CLEAN_LEADS_FILE,
    DEFAULT_COLUMNS,
    FRESH_LEADS_FILE,
    REJECTED_LEADS_FILE,
    atomic_write_dataframe,
    email_domain,
    is_valid_email_format,
    normalize_email,
    now_iso,
    read_csv,
)


def reject(row, reason):
    data = row.to_dict()
    data["rejected_at"] = now_iso()
    data["reason"] = reason
    return data


def scrub_leads(input_path=FRESH_LEADS_FILE, output_path=CLEAN_LEADS_FILE):
    leads = read_csv(input_path, columns=DEFAULT_COLUMNS)
    rejected = []
    accepted = []
    seen_emails = set()
    seen_domains = set()

    for _, row in leads.iterrows():
        row = row.copy()
        row["email"] = normalize_email(row.get("email", ""))
        domain = email_domain(row["email"])

        if all(str(value).strip() == "" for value in row.values):
            rejected.append(reject(row, "blank_row"))
            continue
        if not is_valid_email_format(row["email"]):
            rejected.append(reject(row, "malformed_email"))
            continue
        if row["email"] in seen_emails:
            rejected.append(reject(row, "duplicate_email"))
            continue
        if domain in seen_domains:
            rejected.append(reject(row, "duplicate_domain"))
            continue

        seen_emails.add(row["email"])
        seen_domains.add(domain)
        accepted.append(row.to_dict())

    clean = pd.DataFrame(accepted, columns=DEFAULT_COLUMNS)
    rejects = pd.DataFrame(rejected)

    atomic_write_dataframe(output_path, clean, DEFAULT_COLUMNS)
    if not rejects.empty:
        atomic_write_dataframe(REJECTED_LEADS_FILE, rejects)

    print(f"Clean leads: {len(clean)}. Rejected leads: {len(rejected)}.")


if __name__ == "__main__":
    scrub_leads()
