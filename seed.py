"""
seed.py — Import all provided data into Supabase.

Run once after creating the schema:
  python seed.py

Requires:
  SUPABASE_URL and SUPABASE_KEY in .env
"""

import os
import re
import pandas as pd
from datetime import time
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

DATA_DIR = os.path.dirname(__file__) + "/../"


# ── helpers ──────────────────────────────────────────────────────────────────

NIL_UUID = "00000000-0000-0000-0000-000000000000"

def clear_all():
    """Wipe all tables in reverse dependency order before seeding."""
    tables = [
        "feedback", "order_line_items", "order_sessions", "weekly_orders",
        "session_exclusions", "absences", "manager_overrides",
        "enrollments", "student_dietary", "students",
        "sessions", "menu_items", "caterer_school_coverage", "caterer_contacts",
        "caterers", "schools",
    ]
    for t in tables:
        sb.table(t).delete().neq("id", NIL_UUID).execute()
    print("✓ cleared all tables")

def upsert(table, rows, conflict="id"):
    if rows:
        sb.table(table).insert(rows).execute()

def get_id(table, field, value):
    r = sb.table(table).select("id").eq(field, value).single().execute()
    return r.data["id"]

def parse_time(t: str) -> str:
    """'4:00pm' → '16:00:00'"""
    t = t.strip().lower()
    h, rest = t.split(":")
    m = rest[:2]
    ampm = rest[2:]
    h, m = int(h), int(m)
    if ampm == "pm" and h != 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}:00"


# Wipe all tables first so seed.py is safely re-runnable
clear_all()


# ── 1. Schools ────────────────────────────────────────────────────────────────

schools = [
    {"name": "Moreton Bay Boys' College", "region": "Redlands", "building": "Library"},
    {"name": "John Paul College", "region": "South Brisbane", "building": "G Centre"},
    {"name": "MacGregor State High School", "region": "South Brisbane", "building": "Library"},
    {"name": "Indooroopilly State High School", "region": "West Brisbane", "building": "X Block"},
    {"name": "Loreto College", "region": "Central Brisbane", "building": "Ella Building"},
    {"name": "Cannon Hill Anglican College", "region": "Central Brisbane", "building": "E Centre"},
]
upsert("schools", schools, "name")
print("✓ schools")


# ── 2. Caterers ───────────────────────────────────────────────────────────────

caterers_df = pd.read_excel(DATA_DIR + "caterers.xlsx").dropna(subset=["caterer"])
caterers_df = caterers_df[caterers_df["caterer"].str.strip() != ""].copy()
caterers_df.columns = [c.strip() for c in caterers_df.columns]

# Prices and delivery from the menus PDF (manually extracted)
caterer_meta = {
    "Lakehouse Victoria Point": {
        "price_per_item": 35.00, "price_includes_gst": False,
        "delivery_fee": 0.00, "delivery_fee_type": "per_trip",
    },
    "Terrific Noodles": {
        "price_per_item": 20.50, "price_includes_gst": False,
        "delivery_fee": 30.00, "delivery_fee_type": "per_school_per_trip",
    },
    "Kenko Sushi House": {
        "price_per_item": 5.50, "price_includes_gst": True,
        "delivery_fee": 10.00, "delivery_fee_type": "per_school_per_trip",
    },
    "Guzman y Gomez": {
        "price_per_item": 15.00, "price_includes_gst": True,
        "delivery_fee": 50.00, "delivery_fee_type": "per_trip",
    },
}

caterer_rows = []
for _, row in caterers_df.iterrows():
    name = row["caterer"].strip()
    if name not in caterer_meta:
        continue  # skip footnote/header rows
    meta = caterer_meta[name]
    caterer_rows.append({
        "name": name,
        "region": row["region"].strip(),
        "price_per_item": meta["price_per_item"],
        "price_includes_gst": meta["price_includes_gst"],
        "delivery_fee": meta["delivery_fee"],
        "delivery_fee_type": meta["delivery_fee_type"],
        "min_order_4_items": int(row["minimum order quantity for 4 menu items"]),
        "min_order_5_items": int(row["minimum order quantity for 5 menu items"]),
        "min_order_6_items": int(row["minimum order quantity for 6 menu items"]),
    })
upsert("caterers", caterer_rows, "name")
print("✓ caterers")


# ── 3. Caterer contacts ───────────────────────────────────────────────────────

# Extracted from caterer-contacts.pdf
caterer_contacts_data = {
    "Lakehouse Victoria Point": [
        {"name": "Carmen Gabrielle", "email": "carmen@padea.com.au",
         "role": "primary", "cc_on_orders": True},
    ],
    "Terrific Noodles": [
        {"name": "Dylan Chern", "email": "cherndylan@gmail.com",
         "role": "primary", "cc_on_orders": True},
        # James Chern explicitly does NOT want to be CC'd
        {"name": "James Chern", "email": "dylanchern808@gmail.com",
         "role": "chef", "cc_on_orders": False},
    ],
    "Kenko Sushi House": [
        {"name": "Big Mom", "email": "hellopadea@gmail.com",
         "role": "primary", "cc_on_orders": True},
    ],
    "Guzman y Gomez": [
        {"name": "Big Chicken", "email": "carmengabrielleee@gmail.com",
         "role": "primary", "cc_on_orders": True},
        # Medium Giraffe (chef) DOES want to be CC'd
        {"name": "Medium Giraffe", "email": "dylan@padea.com.au",
         "role": "chef", "cc_on_orders": True},
    ],
}

contact_rows = []
for caterer_name, contacts in caterer_contacts_data.items():
    caterer_id = get_id("caterers", "name", caterer_name)
    for c in contacts:
        contact_rows.append({"caterer_id": caterer_id, **c})
upsert("caterer_contacts", contact_rows, "email")
print("✓ caterer contacts")


# ── 4. Caterer school coverage ────────────────────────────────────────────────

coverage_data = {
    "Lakehouse Victoria Point": {
        "current": ["Moreton Bay Boys' College"],
        "able": ["Cannon Hill Anglican College"],
    },
    "Terrific Noodles": {
        "current": ["John Paul College", "MacGregor State High School"],
        "able": ["Loreto College"],
    },
    "Kenko Sushi House": {
        "current": ["Indooroopilly State High School"],
        "able": [],
    },
    "Guzman y Gomez": {
        "current": ["Loreto College", "Cannon Hill Anglican College"],
        "able": ["MacGregor State High School"],
    },
}

coverage_rows = []
for caterer_name, schools_map in coverage_data.items():
    caterer_id = get_id("caterers", "name", caterer_name)
    for school_name in schools_map["current"]:
        school_id = get_id("schools", "name", school_name)
        coverage_rows.append({"caterer_id": caterer_id, "school_id": school_id, "is_current": True})
    for school_name in schools_map["able"]:
        school_id = get_id("schools", "name", school_name)
        coverage_rows.append({"caterer_id": caterer_id, "school_id": school_id, "is_current": False})
upsert("caterer_school_coverage", coverage_rows)
print("✓ caterer school coverage")


# ── 5. Menu items ─────────────────────────────────────────────────────────────

# Extracted from caterer-menus.pdf
# contains_* flags inferred from item names where not explicitly tagged
menus = {
    "Lakehouse Victoria Point": [
        {"name": "Shrimp Fried Rice", "is_gf": True, "is_df": True, "is_nf": False, "is_vo": False, "contains_shellfish": True},
        {"name": "Spaghetti Bolognese + Garlic Bread", "is_nf": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Sweet and Sour Chicken", "is_gf": True, "is_df": True, "is_nf": True},
        {"name": "Classic Cream Pasta", "is_nf": True, "is_vo": True},
        {"name": "Gnocchi in Tomato Sauce", "is_nf": True, "is_vo": True},
        {"name": "Chicken, Bacon, Avo Wrap", "is_vo": True, "contains_pork": True},  # bacon = pork
        {"name": "Fried Chicken Burger + Chips", "is_nf": True},
        {"name": "Fish Taco Bowl", "is_nf": True, "contains_fish": True},
        {"name": "Korean Beef Bulgogi Rice Bowl", "is_gf": True, "is_df": True, "is_nf": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Japanese Chicken Curry", "is_df": True, "is_nf": True, "is_vo": True},
    ],
    "Terrific Noodles": [
        {"name": "Spicy Miso Udon", "is_df": True, "is_vo": True},
        {"name": "Stir-fry Noodles topped with Chicken", "is_gf": True, "is_df": True, "is_nf": True},
        {"name": "Grilled Pork Vermicelli Salad", "is_gf": True, "is_df": True, "is_nf": True, "is_vo": True, "contains_pork": True},
        {"name": "Spaghetti meatballs", "is_nf": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Lemongrass Grilled Beef and Noodles", "is_gf": True, "is_df": True, "is_nf": True, "is_vo": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Creamy Garlic Beef Noodles", "is_vo": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Mie Goreng", "is_gf": True, "is_df": True, "is_nf": True, "is_vo": True},
        {"name": "Beef Pad Thai", "contains_beef": True, "contains_red_meat": True},
        {"name": "Bacon Carbonara", "contains_pork": True},
        {"name": "Chinese Honey Soy Noodles", "is_df": True},
    ],
    "Kenko Sushi House": [
        {"name": "Lamb wrap", "is_nf": True, "contains_red_meat": True},
        {"name": "Chicken Parmi, chips and salad", "is_df": True, "is_nf": True},
        {"name": "Japanese Chicken Katsu", "is_nf": True, "is_vo": True},
        {"name": "Teriyaki Salmon rice bowl", "is_gf": True, "is_df": True, "is_nf": True, "is_vo": True, "contains_fish": True},
        {"name": "Chicken Karaage ricebowl", "is_df": True, "is_nf": True, "is_vo": True},
        {"name": "Creamy Udon"},
        {"name": "Beef Fried Rice", "is_gf": True, "is_df": True, "is_vo": True, "contains_beef": True, "contains_red_meat": True},
        {"name": "Mongolian Beef and Rice", "contains_beef": True, "contains_red_meat": True},
        {"name": "Sweet and Sour Chicken", "is_gf": True, "is_df": True},
        {"name": "Chinese Honey Soy Noodles", "is_df": True},
    ],
    "Guzman y Gomez": [
        {"name": "Breakfast Tacos", "is_nf": True, "is_vo": True, "contains_pork": True},  # typically includes bacon
        {"name": "Caesar Salad", "is_gf": True, "is_df": True, "is_nf": True, "is_vo": True},
        {"name": "Cali Burrito"},   # typically contains beef/pork
        {"name": "Grilled Chicken Burrito"},
        {"name": "Pulled pork burrito bowl", "is_gf": True, "is_nf": True, "is_vo": True, "contains_pork": True},
        {"name": "Nachos", "is_gf": True, "is_vo": True},
        {"name": "Nacho Fries", "is_gf": True, "is_vo": True},
        {"name": "Chicken Quesadilla"},
        {"name": "Chicken Enchilada", "is_gf": True, "is_df": True},
        {"name": "Crispy Chicken Taco"},
    ],
}

menu_rows = []
for caterer_name, items in menus.items():
    caterer_id = get_id("caterers", "name", caterer_name)
    for item in items:
        row = {
            "caterer_id": caterer_id,
            "is_gf": False, "is_df": False, "is_nf": False, "is_vo": False,
            "contains_pork": False, "contains_shellfish": False,
            "contains_beef": False, "contains_fish": False, "contains_red_meat": False,
        }
        row.update(item)
        menu_rows.append(row)
upsert("menu_items", menu_rows)
print("✓ menu items")


# ── 6. Sessions ───────────────────────────────────────────────────────────────

sessions_df = pd.read_excel(DATA_DIR + "sessions.xlsx")
sessions_df.columns = [c.strip() for c in sessions_df.columns]

session_rows = []
for _, row in sessions_df.iterrows():
    school_id = get_id("schools", "name", row["school"].strip())
    caterer_id = get_id("caterers", "name", row["caterer"].strip())
    year_levels = [int(y.strip()) for y in str(row["year-levels"]).split(",")]
    session_rows.append({
        "school_id": school_id,
        "caterer_id": caterer_id,
        "day_of_week": row["day"].strip(),
        "start_time": parse_time(row["start-time"]),
        "end_time": parse_time(row["end-time"]),
        "dinner_time": parse_time(row["dinner-time"]),
        "building": row["Building"].strip(),
        "default_manager_name": row["manager"].strip(),
        "default_manager_mobile": str(row["manager-mobile"]).strip(),
        "year_levels": year_levels,
    })
upsert("sessions", session_rows)
print("✓ sessions")


# ── 7. Students ───────────────────────────────────────────────────────────────

SHEET_TO_SESSION = {
    "MBBC":            ("Moreton Bay Boys' College",        "Tuesday"),
    "JPC - Tuesday":   ("John Paul College",                "Tuesday"),
    "JPC - Wednesday": ("John Paul College",                "Wednesday"),
    "MSHS":            ("MacGregor State High School",      "Thursday"),
    "ISHS - Monday":   ("Indooroopilly State High School",  "Monday"),
    "ISHS - Tuesday":  ("Indooroopilly State High School",  "Tuesday"),
    "ISHS - Thursday": ("Indooroopilly State High School",  "Thursday"),
    "LC - Monday":     ("Loreto College",                   "Monday"),
    "LC - Tuesday":    ("Loreto College",                   "Tuesday"),
    "CHAC - Monday":   ("Cannon Hill Anglican College",     "Monday"),
    "CHAC - Wednesday":("Cannon Hill Anglican College",     "Wednesday"),
}

# Map dietary text → normalised restriction codes
def parse_dietary(raw):
    if not raw or pd.isna(raw):
        return []
    raw = str(raw).strip()
    result = []
    lower = raw.lower()
    if "opted out" in lower:
        return ["opted_out"]
    if "halal" in lower:
        result.append("halal")
    if "vegetarian" in lower:
        result.append("vegetarian")
    if "nut free" in lower or "nut-free" in lower:
        result.append("nut_free")
    if "gluten free" in lower or "gluten-free" in lower:
        result.append("gluten_free")
    if "dairy free" in lower or "dairy-free" in lower:
        result.append("dairy_free")
    if "no beef" in lower:
        result.append("no_beef")
    if "no pork" in lower:
        result.append("no_pork")
    if "no shellfish" in lower:
        result.append("no_shellfish")
    if "no fish" in lower:
        result.append("no_fish")
    if "no seafood" in lower:
        result.append("no_shellfish")
        result.append("no_fish")
    if "no red meat" in lower:
        result.append("no_red_meat")
    return list(set(result))

students_xl = pd.read_excel(DATA_DIR + "students.xlsx", sheet_name=None)

# Track inserted students by email to avoid duplicates across sheets
inserted_students = {}  # email -> student_id
student_rows_to_insert = []
dietary_rows = []
enrollment_rows = []

for sheet_name, df in students_xl.items():
    if sheet_name not in SHEET_TO_SESSION:
        print(f"  ⚠ unknown sheet: {sheet_name}")
        continue

    school_name, day = SHEET_TO_SESSION[sheet_name]
    school_id = get_id("schools", "name", school_name)

    # Find the session id
    sessions_resp = (
        sb.table("sessions")
        .select("id")
        .eq("school_id", school_id)
        .eq("day_of_week", day)
        .single()
        .execute()
    )
    session_id = sessions_resp.data["id"]

    # Row 1 (index 1) is the header in each sheet
    df.columns = df.iloc[1].tolist()
    df = df.iloc[2:].reset_index(drop=True)
    df = df.dropna(subset=["Student"])

    for _, row in df.iterrows():
        name = str(row.get("Student", "")).strip()
        if not name:
            continue

        year_level = int(row.get("Year Level", 0))
        email = str(row.get("Student Email", "")).strip()
        dietary_raw = row.get("Dietary", "")
        dietary = parse_dietary(dietary_raw)
        opted_out = "opted_out" in dietary

        if opted_out:
            dietary = []  # store opted_out as flag on student, not as dietary restriction

        student_key = email if email and email != "nan" else name.lower().replace(" ", "_")

        if student_key not in inserted_students:
            student_row = {
                "name": name,
                "year_level": year_level,
                "student_email": email if email and email != "nan" else None,
                "parent_name": str(row.get("Parent", "")).strip() or None,
                "parent_email": str(row.get("Parent Email", "")).strip() or None,
                "parent_mobile": str(row.get("Parent Mobile", "")).strip() or None,
                "opted_out_of_catering": opted_out,
            }
            student_rows_to_insert.append(student_row)
            inserted_students[student_key] = None  # will be filled after insert

# Insert students in bulk, then fetch IDs
if student_rows_to_insert:
    result = sb.table("students").upsert(student_rows_to_insert).execute()
    # Rebuild key → id map
    all_students = sb.table("students").select("id,name,student_email").execute().data
    for s in all_students:
        key = s["student_email"] if s["student_email"] else s["name"].lower().replace(" ", "_")
        inserted_students[key] = s["id"]

# Second pass: dietary + enrollments
for sheet_name, df in students_xl.items():
    if sheet_name not in SHEET_TO_SESSION:
        continue
    school_name, day = SHEET_TO_SESSION[sheet_name]
    school_id = get_id("schools", "name", school_name)
    sessions_resp = (
        sb.table("sessions")
        .select("id")
        .eq("school_id", school_id)
        .eq("day_of_week", day)
        .single()
        .execute()
    )
    session_id = sessions_resp.data["id"]

    df.columns = df.iloc[1].tolist()
    df = df.iloc[2:].reset_index(drop=True)
    df = df.dropna(subset=["Student"])

    for _, row in df.iterrows():
        name = str(row.get("Student", "")).strip()
        if not name:
            continue
        email = str(row.get("Student Email", "")).strip()
        dietary_raw = row.get("Dietary", "")
        dietary = parse_dietary(dietary_raw)
        opted_out = "opted_out" in dietary
        if opted_out:
            dietary = []

        student_key = email if email and email != "nan" else name.lower().replace(" ", "_")
        student_id = inserted_students.get(student_key)
        if not student_id:
            continue

        for restriction in dietary:
            dietary_rows.append({"student_id": student_id, "restriction": restriction})

        enrollment_rows.append({"student_id": student_id, "session_id": session_id})

upsert("student_dietary", dietary_rows)
upsert("enrollments", enrollment_rows)
print("✓ students + dietary + enrollments")


# ── 8. Absences (from absences.pdf — manually extracted) ─────────────────────

# Format: (student_name, school_name, day_of_week, date)
absences_raw = [
    # Week of 2026-05-04: Mon=04, Tue=05, Wed=06, Thu=07
    ("Noah Baker",       "Moreton Bay Boys' College",        "Tuesday",   "2026-05-05"),
    ("Christina Hu",     "John Paul College",                "Tuesday",   "2026-05-05"),
    ("Nathan Smith",     "John Paul College",                "Tuesday",   "2026-05-05"),
    ("Rose Smith",       "MacGregor State High School",      "Thursday",  "2026-05-07"),
    ("Charlie Morris",   "Indooroopilly State High School",  "Tuesday",   "2026-05-05"),
    ("Jack Carter",      "Indooroopilly State High School",  "Tuesday",   "2026-05-05"),
    ("Charlie Mitchell", "Indooroopilly State High School",  "Tuesday",   "2026-05-05"),
    ("Holly Hill",       "Loreto College",                   "Monday",    "2026-05-04"),
    ("Imogen Evans",     "Loreto College",                   "Monday",    "2026-05-04"),
    ("Henry Cook",       "Cannon Hill Anglican College",     "Wednesday", "2026-05-06"),
]

# NOTE: The absences.pdf lists dates in May 2026 (01-04 May). These appear to be
# for a specific week. The system should store absences with exact dates.
# For seeding we use the dates as given in the PDF.
absence_rows = []
for student_name, school_name, day, date_str in absences_raw:
    # Find student by name
    student_resp = sb.table("students").select("id").ilike("name", student_name).execute()
    if not student_resp.data:
        print(f"  ⚠ absent student not found: {student_name}")
        continue
    student_id = student_resp.data[0]["id"]

    school_id = get_id("schools", "name", school_name)
    session_resp = (
        sb.table("sessions")
        .select("id")
        .eq("school_id", school_id)
        .eq("day_of_week", day)
        .single()
        .execute()
    )
    if not session_resp.data:
        print(f"  ⚠ session not found: {school_name} {day}")
        continue
    session_id = session_resp.data["id"]
    absence_rows.append({
        "student_id": student_id,
        "session_id": session_id,
        "absence_date": date_str,
    })

upsert("absences", absence_rows)
print("✓ absences")


# ── 9. Session exclusions (from exclusions.pdf) ───────────────────────────────

exclusions_raw = [
    # (school, day, date, year_levels_excluded, reason)
    # [] or None = all year levels (full cancellation)
    ("Indooroopilly State High School", "Thursday", "2026-05-07", [],        "Open Day"),
    ("Loreto College",                  "Tuesday",  "2026-05-05", [],        "Parent Teacher Interviews"),
    ("Cannon Hill Anglican College",    "Wednesday","2026-05-06", [12, 10],  "School Camp"),
]

exclusion_rows = []
for school_name, day, date_str, year_levels_excluded, reason in exclusions_raw:
    school_id = get_id("schools", "name", school_name)
    session_resp = (
        sb.table("sessions")
        .select("id")
        .eq("school_id", school_id)
        .eq("day_of_week", day)
        .single()
        .execute()
    )
    if not session_resp.data:
        print(f"  ⚠ session not found: {school_name} {day}")
        continue
    session_id = session_resp.data["id"]
    exclusion_rows.append({
        "session_id": session_id,
        "exclusion_date": date_str,
        "year_levels_excluded": year_levels_excluded if year_levels_excluded else None,
        "reason": reason,
    })

upsert("session_exclusions", exclusion_rows)
print("✓ session exclusions")

print("\n✅ Seed complete.")
