"""
generate_order.py — Weekly catering order generator.

Run every Thursday to generate and send orders for next week:
  python generate_order.py [--week YYYY-MM-DD] [--dry-run]

  --week: Monday of the target week (default: next Monday)
  --dry-run: print emails without sending
"""

import os
import json
import argparse
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client
from google import genai

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Maps day name → date offset from Monday (0=Mon, 1=Tue, ...)
DAY_OFFSET = {d: i for i, d in enumerate(DAY_ORDER)}


# ── date helpers ──────────────────────────────────────────────────────────────

def next_monday(from_date: date = None) -> date:
    d = from_date or date.today()
    days_ahead = (7 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)

def session_date(week_monday: date, day_name: str) -> date:
    return week_monday + timedelta(days=DAY_OFFSET[day_name])


# ── attendance calculation ────────────────────────────────────────────────────

def get_attendance(session_id: str, target_date: date) -> dict:
    """
    Returns:
      meal_count: int
      dietary_summary: list of restriction strings that apply to ≥1 student
      manager_name: str
      manager_mobile: str
    """
    # Get session details
    sess = sb.table("sessions").select("*").eq("id", session_id).single().execute().data

    # Check for full cancellation
    excl = (
        sb.table("session_exclusions")
        .select("*")
        .eq("session_id", session_id)
        .eq("exclusion_date", str(target_date))
        .execute()
        .data
    )
    full_cancel = any(
        (not e["year_levels_excluded"] or len(e["year_levels_excluded"]) == 0)
        for e in excl
    )
    if full_cancel:
        reason = excl[0]["reason"] if excl else "unknown"
        return {"cancelled": True, "reason": reason}

    excluded_year_levels = set()
    for e in excl:
        if e["year_levels_excluded"]:
            excluded_year_levels.update(e["year_levels_excluded"])

    # Get enrolled students
    enrollments = (
        sb.table("enrollments")
        .select("student_id")
        .eq("session_id", session_id)
        .execute()
        .data
    )
    student_ids = [e["student_id"] for e in enrollments]

    if not student_ids:
        return {"cancelled": False, "meal_count": 0, "dietary_summary": [], "students": []}

    # Get full student records
    students = (
        sb.table("students")
        .select("id,name,year_level,opted_out_of_catering")
        .in_("id", student_ids)
        .execute()
        .data
    )

    # Get absences for this session on this date
    absences = (
        sb.table("absences")
        .select("student_id")
        .eq("session_id", session_id)
        .eq("absence_date", str(target_date))
        .execute()
        .data
    )
    absent_ids = {a["student_id"] for a in absences}

    # Filter students
    attending = [
        s for s in students
        if not s["opted_out_of_catering"]
        and s["id"] not in absent_ids
        and s["year_level"] not in excluded_year_levels
    ]

    if not attending:
        return {"cancelled": False, "meal_count": 0, "dietary_summary": [], "students": []}

    # Get dietary restrictions for attending students
    attending_ids = [s["id"] for s in attending]
    dietary = (
        sb.table("student_dietary")
        .select("student_id,restriction")
        .in_("student_id", attending_ids)
        .execute()
        .data
    )
    dietary_summary = list(set(d["restriction"] for d in dietary))

    # Check for manager override
    override = (
        sb.table("manager_overrides")
        .select("*")
        .eq("session_id", session_id)
        .eq("override_date", str(target_date))
        .execute()
        .data
    )
    manager_name = override[0]["manager_name"] if override else sess["default_manager_name"]
    manager_mobile = override[0]["manager_mobile"] if override else sess["default_manager_mobile"]

    return {
        "cancelled": False,
        "meal_count": len(attending),
        "dietary_summary": dietary_summary,
        "manager_name": manager_name,
        "manager_mobile": manager_mobile,
        "building": sess["building"],
        "dinner_time": sess["dinner_time"],
        "students": [s["name"] for s in attending],
    }


# ── meal selection via Claude ─────────────────────────────────────────────────

def select_meals_mock(caterer: dict, sessions_for_caterer: list, menu_items: list) -> dict:
    """Mock meal selection — picks the first N restriction-safe items evenly. Used with --mock-ai."""
    total_meals = sum(s["meal_count"] for s in sessions_for_caterer)

    # Collect all restrictions across every session for this caterer
    all_restrictions = set()
    for s in sessions_for_caterer:
        all_restrictions.update(s.get("dietary_summary", []))

    # Filter out items that violate any hard restriction
    def is_safe(item):
        if ("halal" in all_restrictions or "no_pork" in all_restrictions) and item.get("contains_pork"):
            return False
        if "no_beef" in all_restrictions and item.get("contains_beef"):
            return False
        if "no_shellfish" in all_restrictions and item.get("contains_shellfish"):
            return False
        if "no_fish" in all_restrictions and item.get("contains_fish"):
            return False
        if "no_red_meat" in all_restrictions and item.get("contains_red_meat"):
            return False
        return True

    safe_items = [item for item in menu_items if is_safe(item)]
    if len(safe_items) < 4:
        safe_items = menu_items  # fallback if filtering leaves too few options

    if total_meals >= caterer["min_order_6_items"]:
        max_items = 6
    elif total_meals >= caterer["min_order_5_items"]:
        max_items = 5
    else:
        max_items = 4

    selected = [item["name"] for item in safe_items[:max_items]]
    session_allocations = {}
    for s in sessions_for_caterer:
        key = f"{s['school_name']} {s['day_of_week']}"
        count = s["meal_count"]
        per_item = count // len(selected)
        remainder = count % len(selected)
        alloc = {item: per_item for item in selected}
        alloc[selected[0]] += remainder
        session_allocations[key] = alloc

    return {
        "selected_items": selected,
        "session_allocations": session_allocations,
        "reasoning": "[mock] First N restriction-safe items selected evenly for demo purposes.",
    }


def select_meals(caterer: dict, sessions_for_caterer: list, menu_items: list) -> dict:
    """
    Ask Gemini to select menu items and quantities for this caterer's sessions.

    Returns: {session_id: {menu_item_name: quantity, ...}, ...}
    """
    # Build context
    menu_text = "\n".join(
        f"  - {item['name']}"
        + (" [GF]" if item["is_gf"] else "")
        + (" [DF]" if item["is_df"] else "")
        + (" [NF]" if item["is_nf"] else "")
        + (" [Vegetarian]" if item["is_vo"] else "")
        + (" [contains pork]" if item["contains_pork"] else "")
        + (" [contains beef]" if item["contains_beef"] else "")
        + (" [contains shellfish]" if item["contains_shellfish"] else "")
        + (" [contains fish]" if item["contains_fish"] else "")
        + (" [contains red meat]" if item["contains_red_meat"] else "")
        for item in menu_items
    )

    sessions_text = ""
    total_meals = 0
    for s in sessions_for_caterer:
        total_meals += s["meal_count"]
        dietary_str = ", ".join(s["dietary_summary"]) if s["dietary_summary"] else "none"
        sessions_text += (
            f"\n  Session: {s['school_name']} ({s['day_of_week']}, {s['session_date']})\n"
            f"    Meals needed: {s['meal_count']}\n"
            f"    Active dietary restrictions: {dietary_str}\n"
        )

    # Determine how many menu items can be offered based on minimum order
    if total_meals >= caterer["min_order_6_items"]:
        max_items = 6
    elif total_meals >= caterer["min_order_5_items"]:
        max_items = 5
    else:
        max_items = 4

    # Get recent feedback for this caterer's menu items only
    menu_item_ids = {item["id"]: item["name"] for item in menu_items}
    feedback_resp = (
        sb.table("feedback")
        .select("menu_item_id,overall_rating,quality_rating,notes,session_date")
        .in_("menu_item_id", list(menu_item_ids.keys()))
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    feedback_text = ""
    if feedback_resp:
        for f in feedback_resp:
            item_name = menu_item_ids.get(f["menu_item_id"], "unknown")
            feedback_text += f"  - {item_name}: {f['overall_rating']}/5"
            if f["quality_rating"]:
                feedback_text += f" (quality: {f['quality_rating']}/5)"
            if f["notes"]:
                feedback_text += f" — {f['notes']}"
            feedback_text += "\n"

    prompt = f"""You are selecting meals for Padea tutoring sessions. Padea runs small-group tutoring for high school students, and the dinner break is an important part of the student experience. Your goal is to select meals that:
1. Satisfy every student's dietary restriction (critical — this is a hard constraint)
2. Are varied and appealing to high school students
3. Rotate well over time to prevent repetition

CATERER: {caterer['name']}
PRICE: ${caterer['price_per_item']} per meal {'(inc GST)' if caterer['price_includes_gst'] else '(ex GST)'}

MENU (items you may choose from):
{menu_text}

DIETARY RULES:
- "halal" students: avoid pork. All non-pork items on this menu are halal.
- "vegetarian" students: must have at least one vegetarian option [marked Vegetarian]
- "nut_free": must have at least one nut-free option [NF]
- "gluten_free": must have at least one gluten-free option [GF]
- "dairy_free": must have at least one dairy-free option [DF]
- "no_beef": must have at least one option that does not contain beef
- "no_pork": must have at least one option that does not contain pork
- "no_shellfish": must have at least one option that does not contain shellfish
- "no_fish": must have at least one option that does not contain fish
- "no_red_meat": must have at least one option that does not contain red meat
- IMPORTANT: a student with halal + vegetarian needs an option that satisfies BOTH constraints simultaneously

SESSIONS THIS WEEK:
{sessions_text}
TOTAL MEALS: {total_meals}

MENU ITEM LIMIT: Select exactly {max_items} menu items (this is the maximum the caterer can offer given this week's order volume).

PAST FEEDBACK (most recent first):
{feedback_text if feedback_text else "  No feedback yet."}

INSTRUCTIONS:
- Select exactly {max_items} menu items from the menu above
- For each session, allocate meal quantities for each selected item such that quantities sum to that session's meal count
- Ensure dietary constraints are met: every student with a restriction must have ≥1 item they can eat
- Prefer popular items (high feedback ratings) and avoid items with declining quality
- Return ONLY valid JSON in this exact format (no explanation text):

{{
  "selected_items": ["item name 1", "item name 2", ...],
  "session_allocations": {{
    "<school_name> <day>": {{
      "item name 1": <quantity>,
      "item name 2": <quantity>
    }}
  }},
  "reasoning": "brief explanation of choices"
}}

The session keys in session_allocations must exactly match "{sessions_for_caterer[0]['school_name']} {sessions_for_caterer[0]['day_of_week']}" format.
"""

    response = gemini.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
    )
    raw = response.text.strip()

    # Strip any markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


# ── email generation ──────────────────────────────────────────────────────────

def build_order_email(caterer: dict, contacts: list, sessions_data: list, meal_selection: dict) -> dict:
    """Build the order email to/cc fields and body."""
    to_emails = [c["email"] for c in contacts if c["role"] == "primary"]
    cc_emails = [c["email"] for c in contacts if c["cc_on_orders"] and c["role"] != "primary"]

    seen = set()
    unique_schools = []
    for s in sessions_data:
        if s["school_name"] not in seen:
            seen.add(s["school_name"])
            unique_schools.append(s["school_name"])
    school_names = " & ".join(unique_schools)
    week_dates = sorted(s["session_date"] for s in sessions_data)
    week_str = f"week of {week_dates[0].strftime('%d %b %Y')}"

    allocations = meal_selection.get("session_allocations", {})

    lines = []
    lines.append(f"Hi {contacts[0]['name'].split()[0]},")
    lines.append("")
    lines.append(
        f"Please find below our catering order for {school_names} for the {week_str}."
    )
    lines.append("")

    total_meals = 0
    for s in sessions_data:
        key = f"{s['school_name']} {s['day_of_week']}"
        session_alloc = allocations.get(key, {})
        session_total = sum(session_alloc.values())
        total_meals += session_total

        lines.append(f"{'─' * 60}")
        lines.append(
            f"School:    {s['school_name']}"
        )
        lines.append(
            f"Date:      {s['session_date'].strftime('%A, %d %B %Y')}"
        )
        lines.append(
            f"Delivery:  {s['dinner_time']} (please arrive 5–10 min before)"
        )
        lines.append(
            f"Location:  {s['building']}"
        )
        lines.append(
            f"On-site:   {s['manager_name']} — {s['manager_mobile']}"
        )
        lines.append("")
        lines.append("Order:")
        for item_name, qty in session_alloc.items():
            lines.append(f"  {item_name}: {qty}")
        lines.append(f"  TOTAL: {session_total} meals")
        lines.append("")

    lines.append(f"{'─' * 60}")
    lines.append(f"Grand total this week: {total_meals} meals")
    lines.append("")
    lines.append(
        "Please confirm receipt of this order and let us know if you have any questions."
    )
    lines.append("")
    lines.append("Thanks,")
    lines.append("Padea Program Coordinator")

    subject = f"Padea catering order — {school_names} — {week_str}"
    body = "\n".join(lines)

    return {
        "to": to_emails,
        "cc": cc_emails,
        "subject": subject,
        "body": body,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run(week_monday: date, dry_run: bool, mock_ai: bool = False):
    print(f"\n{'='*60}")
    print(f"Generating orders for week of {week_monday}")
    print(f"{'='*60}\n")

    # Get all sessions
    all_sessions = sb.table("sessions").select("*").execute().data

    # Group by caterer
    caterer_sessions: dict[str, list] = {}
    for sess in all_sessions:
        target_date = session_date(week_monday, sess["day_of_week"])
        attendance = get_attendance(sess["id"], target_date)

        school = sb.table("schools").select("name").eq("id", sess["school_id"]).single().execute().data

        if attendance.get("cancelled"):
            print(f"  ✗ CANCELLED: {school['name']} {sess['day_of_week']} ({target_date}) — {attendance['reason']}")
            continue

        if attendance["meal_count"] == 0:
            print(f"  ✗ 0 meals: {school['name']} {sess['day_of_week']} ({target_date}) — skipping")
            continue

        caterer_id = sess["caterer_id"]
        if caterer_id not in caterer_sessions:
            caterer_sessions[caterer_id] = []

        caterer_sessions[caterer_id].append({
            "session_id": sess["id"],
            "school_name": school["name"],
            "day_of_week": sess["day_of_week"],
            "session_date": target_date,
            "building": attendance["building"],
            "dinner_time": attendance["dinner_time"],
            "manager_name": attendance["manager_name"],
            "manager_mobile": attendance["manager_mobile"],
            "meal_count": attendance["meal_count"],
            "dietary_summary": attendance["dietary_summary"],
        })
        print(
            f"  ✓ {school['name']} {sess['day_of_week']} ({target_date}): "
            f"{attendance['meal_count']} meals, restrictions: {attendance['dietary_summary'] or 'none'}"
        )

    print()

    # For each caterer, select meals and build email
    for caterer_id, sessions_data in caterer_sessions.items():
        caterer = sb.table("caterers").select("*").eq("id", caterer_id).single().execute().data
        contacts = sb.table("caterer_contacts").select("*").eq("caterer_id", caterer_id).execute().data
        menu_items = sb.table("menu_items").select("*").eq("caterer_id", caterer_id).execute().data

        print(f"─── {caterer['name']} ({len(sessions_data)} session(s)) ───")

        # Check minimum order
        total_meals = sum(s["meal_count"] for s in sessions_data)
        min_4 = caterer["min_order_4_items"]
        if total_meals < min_4:
            print(
                f"  ⚠ WARNING: {total_meals} meals is below minimum of {min_4} for 4 items."
                f" Contact {caterer['name']} to negotiate."
            )

        print(f"  Total meals: {total_meals}")

        # Select meals
        if mock_ai:
            print("  [mock-ai] Selecting meals without AI call...")
            meal_selection = select_meals_mock(caterer, sessions_data, menu_items)
        else:
            print("  Asking Gemini to select meals...")
            meal_selection = select_meals(caterer, sessions_data, menu_items)
        print(f"  Selected: {meal_selection.get('selected_items', [])}")
        print(f"  Reasoning: {meal_selection.get('reasoning', '')[:200]}")

        # Build email
        email = build_order_email(caterer, contacts, sessions_data, meal_selection)

        print(f"\n  EMAIL TO: {', '.join(email['to'])}")
        if email["cc"]:
            print(f"  EMAIL CC: {', '.join(email['cc'])}")
        print(f"  SUBJECT:  {email['subject']}")
        print()
        print(email["body"])
        print()

        # Save to DB
        if not dry_run:
            order_resp = (
                sb.table("weekly_orders")
                .upsert({
                    "caterer_id": caterer_id,
                    "week_start_date": str(week_monday),
                    "status": "draft",
                    "email_subject": email["subject"],
                    "email_body": email["body"],
                })
                .execute()
            )
            order_id = order_resp.data[0]["id"]

            for s in sessions_data:
                key = f"{s['school_name']} {s['day_of_week']}"
                alloc = meal_selection.get("session_allocations", {}).get(key, {})

                os_resp = sb.table("order_sessions").upsert({
                    "order_id": order_id,
                    "session_id": s["session_id"],
                    "session_date": str(s["session_date"]),
                    "meal_count": s["meal_count"],
                    "manager_name": s["manager_name"],
                    "manager_mobile": s["manager_mobile"],
                }).execute()
                order_session_id = os_resp.data[0]["id"]

                for item_name, qty in alloc.items():
                    item = next((m for m in menu_items if m["name"] == item_name), None)
                    if item and qty > 0:
                        sb.table("order_line_items").upsert({
                            "order_session_id": order_session_id,
                            "menu_item_id": item["id"],
                            "quantity": qty,
                        }).execute()

            print(f"  ✓ Saved order {order_id} to database (status: draft)")
            print(f"  → Run send_orders.py to send emails.\n")
        else:
            print("  [dry-run: not saved]\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", help="Monday of target week (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock-ai", action="store_true", help="Skip AI call; use mock meal selection")
    args = parser.parse_args()

    if args.week:
        from datetime import datetime
        monday = datetime.strptime(args.week, "%Y-%m-%d").date()
    else:
        monday = next_monday()

    run(monday, args.dry_run, args.mock_ai)
