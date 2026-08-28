import argparse
from pathlib import Path

import pandas as pd

from aurum_core import DEFAULT_COLUMNS, FRESH_LEADS_FILE, atomic_write_dataframe, read_csv

FIELD_ALIASES = {
    "name": ["name", "first_name", "contact_name", "founder_name", "person"],
    "company": ["company", "company_name", "brand", "store_name", "organization"],
    "email": ["email", "email_address", "work_email", "contact_email"],
    "website": ["website", "url", "domain", "store_url"],
    "subject_line": ["subject_line", "subject", "email_subject"],
    "full_email": ["full_email", "email_body", "body", "message"],
}


def find_column(columns, aliases):
    normalized = {column.lower().strip(): column for column in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def normalize_import(path):
    source = pd.read_csv(path, dtype=str).fillna("")
    output = pd.DataFrame(columns=DEFAULT_COLUMNS)

    for field, aliases in FIELD_ALIASES.items():
        source_column = find_column(source.columns, aliases)
        output[field] = source[source_column].astype(str).str.strip() if source_column else ""

    output["email"] = output["email"].str.lower()

    missing_subject = output["subject_line"] == ""
    output.loc[missing_subject, "subject_line"] = output.loc[missing_subject].apply(
        lambda row: f"Quick idea for {row['company'] or 'your brand'}",
        axis=1,
    )

    missing_body = output["full_email"] == ""
    output.loc[missing_body, "full_email"] = output.loc[missing_body].apply(
        lambda row: (
            f"Hi {row['name'] or 'there'},\n\n"
            f"I had a quick idea for {row['company'] or 'your brand'} and wanted to reach out.\n\n"
            "Best,\nAurum Studios"
        ),
        axis=1,
    )

    return output


def import_leads(paths, output_path=FRESH_LEADS_FILE, append=True):
    imported = [normalize_import(Path(path)) for path in paths]
    new_leads = pd.concat(imported, ignore_index=True) if imported else pd.DataFrame(columns=DEFAULT_COLUMNS)

    if append:
        existing = read_csv(output_path, columns=DEFAULT_COLUMNS)
        new_leads = pd.concat([existing, new_leads], ignore_index=True)

    atomic_write_dataframe(output_path, new_leads, DEFAULT_COLUMNS)
    return len(new_leads)


def main():
    parser = argparse.ArgumentParser(description="Import and normalize lead CSV files.")
    parser.add_argument("files", nargs="+", help="CSV files to import.")
    parser.add_argument("--replace", action="store_true", help="Replace fresh_leads.csv instead of appending.")
    args = parser.parse_args()

    count = import_leads(args.files, append=not args.replace)
    print(f"Imported lead pool now contains {count} rows.")


if __name__ == "__main__":
    main()
