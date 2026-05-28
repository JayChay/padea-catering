"""
add_feedback.py — Submit post-session meal feedback.

Run after a session to log how students rated the meals:
  python add_feedback.py

The script walks you through selecting a session, then prompts for
a rating (1-5) on each menu item served by that session's caterer.
Press Enter to skip an item if it wasn't ordered or you have no feedback.
"""

import os
from datetime import date, datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def pick_from_list(prompt, items, label_fn):
    """Print a numbered list and return the selected item."""
    print(f"\n{prompt}")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {label_fn(item)}")
    while True:
        try:
            choice = int(input("\nEnter number: ").strip())
            if 1 <= choice <= len(items):
                return items[choice - 1]
        except (ValueError, KeyboardInterrupt):
            pass
        print("  Please enter a valid number.")


def get_rating(prompt):
    """Prompt for a 1-5 rating. Returns None if skipped."""
    while True:
        raw = input(f"  {prompt} (1-5, or Enter to skip): ").strip()
        if raw == "":
            return None
        try:
            val = int(raw)
            if 1 <= val <= 5:
                return val
        except ValueError:
            pass
        print("  Please enter a number between 1 and 5, or press Enter to skip.")


def main():
    print("\n===== Padea Meal Feedback =====")
    print("This logs post-session feedback so the AI can improve meal selections over time.\n")

    # Step 1: pick a session
    sessions_raw = sb.table("sessions").select("id,day_of_week,school_id,caterer_id").execute().data
    schools = {s["id"]: s["name"] for s in sb.table("schools").select("id,name").execute().data}
    caterers = {c["id"]: c["name"] for c in sb.table("caterers").select("id,name").execute().data}

    session = pick_from_list(
        "Which session are you submitting feedback for?",
        sessions_raw,
        lambda s: f"{schools.get(s['school_id'], '?')} — {s['day_of_week']} ({caterers.get(s['caterer_id'], '?')})",
    )
    school_name = schools.get(session["school_id"], "Unknown school")
    caterer_name = caterers.get(session["caterer_id"], "Unknown caterer")

    # Step 2: pick the session date
    date_str = input(f"\nWhat date did this session run? (YYYY-MM-DD, e.g. 2026-05-06): ").strip()
    try:
        session_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        print("Invalid date format. Exiting.")
        return

    # Step 3: get menu items for this caterer
    menu_items = (
        sb.table("menu_items")
        .select("id,name")
        .eq("caterer_id", session["caterer_id"])
        .execute()
        .data
    )

    if not menu_items:
        print(f"No menu items found for {caterer_name}. Exiting.")
        return

    print(f"\nSession: {school_name} on {session_date} ({caterer_name})")
    submitted_by = input("Your name (for the record): ").strip() or "unknown"

    print(f"\nRate each menu item below. You can skip items that weren't ordered.\n")

    feedback_entries = []
    for item in menu_items:
        print(f"\n  [{item['name']}]")
        overall = get_rating("Overall student enjoyment")
        if overall is None:
            print("  Skipped.")
            continue
        quality = get_rating("Food quality / presentation")
        notes = input("  Any notes? (optional, press Enter to skip): ").strip() or None

        feedback_entries.append({
            "session_id": session["id"],
            "session_date": str(session_date),
            "menu_item_id": item["id"],
            "overall_rating": overall,
            "quality_rating": quality,
            "notes": notes,
            "submitted_by": submitted_by,
        })

    if not feedback_entries:
        print("\nNo feedback entered. Nothing saved.")
        return

    # Save to database
    sb.table("feedback").insert(feedback_entries).execute()

    print(f"\n✓ Saved {len(feedback_entries)} feedback entries for {school_name} on {session_date}.")
    print("  The AI will factor this in next time it selects meals for this caterer.\n")


if __name__ == "__main__":
    main()
