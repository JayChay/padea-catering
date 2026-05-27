# padea-catering

Automates Padea's weekly catering order process. Run every Thursday to calculate attendance, check dietary restrictions, select meals using AI, and generate order emails for each caterer.

## What it does

Each week Padea's program coordinator manually works out how many students are attending each tutoring session, figures out their dietary restrictions, picks meals from each caterer's menu, and writes the order emails. This script does all of that automatically.

Given a target week it:
- Calculates meal counts per session (enrolled students minus absences minus cancelled year levels)
- Aggregates dietary restrictions across all attending students
- Uses Gemini AI to pick appropriate meals from each caterer's menu
- Generates formatted order emails with correct contacts, delivery times, and on-site details
- Handles CC logic per caterer contact

## Edge cases handled

- Full session cancellations (e.g. school Open Day, Parent-Teacher Interviews) - session skipped entirely, no email sent
- Partial year-level exclusions (e.g. Year 10 and 12 on camp, only Year 11 attending) - meal count recalculated for remaining cohort
- Student absences on specific dates - subtracted from that session's count only
- Dietary restriction aggregation - if any student is halal/gluten-free/etc, the whole session order must satisfy that restriction
- Multi-school caterers - one consolidated email per caterer covering all their sessions that week
- Caterer CC preferences - some contacts want Dylan CC'd, others don't, handled per contact

## Setup

1. Clone the repo and install dependencies:
```
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your credentials:
```
cp .env.example .env
```

Required values:
- `SUPABASE_URL` and `SUPABASE_KEY` - from your Supabase project settings
- `GEMINI_API_KEY` - from Google AI Studio

3. Create the database schema in Supabase by running the SQL in `schema.sql` via the Supabase SQL editor.

4. Seed the database with demo data:
```
python3 seed.py
```

## Running

Preview orders for a given week without saving anything:
```
python3 generate_order.py --week 2026-05-04 --dry-run
```

Use `--mock-ai` to skip the Gemini API call and select meals using a simple fallback (useful if API quota is unavailable):
```
python3 generate_order.py --week 2026-05-04 --dry-run --mock-ai
```

Send saved draft orders via email (requires SMTP config in `.env`):
```
python3 send_orders.py
```

## Tech stack

- Python 3
- Supabase (PostgreSQL)
- Google Gemini API (`google-genai`)
- `python-dotenv`, `supabase`, `pandas`, `openpyxl`

## Files

| File | Purpose |
|---|---|
| `schema.sql` | Full 16-table database schema |
| `seed.py` | Populates the database with demo data for the week of 2026-05-04 |
| `generate_order.py` | Main script - calculates attendance, selects meals, generates emails |
| `send_orders.py` | Sends draft orders saved to the database via SMTP |
| `process_diagram.md` | Mermaid flowchart of the full process from order to delivery |
