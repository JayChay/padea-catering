"""
send_orders.py — Send drafted orders via email.

Run after generate_order.py (which creates orders in 'draft' status):
  python send_orders.py [--week YYYY-MM-DD] [--dry-run]
"""

import os
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)
FROM_NAME = os.environ.get("FROM_NAME", "Padea Program Coordinator")


def send_email(to: list, cc: list, subject: str, body: str, dry_run: bool):
    if dry_run:
        print(f"  [dry-run] Would send to: {', '.join(to)}")
        if cc:
            print(f"  [dry-run] Would CC: {', '.join(cc)}")
        return

    msg = MIMEMultipart()
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        all_recipients = to + cc
        server.sendmail(FROM_EMAIL, all_recipients, msg.as_string())

    print(f"  ✓ Sent to {', '.join(to)}" + (f" (CC: {', '.join(cc)})" if cc else ""))


def next_monday(from_date: date = None) -> date:
    d = from_date or date.today()
    days_ahead = (7 - d.weekday()) % 7 or 7
    return d + timedelta(days=days_ahead)


def run(week_monday: date, dry_run: bool):
    orders = (
        sb.table("weekly_orders")
        .select("*, caterers(name)")
        .eq("week_start_date", str(week_monday))
        .eq("status", "draft")
        .execute()
        .data
    )

    if not orders:
        print(f"No draft orders found for week of {week_monday}.")
        return

    for order in orders:
        caterer_id = order["caterer_id"]
        caterer_name = order["caterers"]["name"]
        contacts = (
            sb.table("caterer_contacts")
            .select("*")
            .eq("caterer_id", caterer_id)
            .execute()
            .data
        )
        to = [c["email"] for c in contacts if c["role"] == "primary"]
        cc = [c["email"] for c in contacts if c["cc_on_orders"] and c["role"] != "primary"]

        print(f"Sending order to {caterer_name}...")
        send_email(to, cc, order["email_subject"], order["email_body"], dry_run)

        if not dry_run:
            from datetime import datetime, timezone
            sb.table("weekly_orders").update({
                "status": "sent",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order["id"]).execute()

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", help="Monday of target week (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.week:
        from datetime import datetime
        monday = datetime.strptime(args.week, "%Y-%m-%d").date()
    else:
        monday = next_monday()

    run(monday, args.dry_run)
