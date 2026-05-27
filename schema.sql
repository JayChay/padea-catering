-- Padea Catering System — Supabase Schema
-- Run this in Supabase SQL editor to set up all tables.

-- Schools
create table schools (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  region text not null,
  building text  -- default session building (can be overridden per session)
);

-- Caterers
create table caterers (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  region text not null,
  price_per_item numeric(10,2) not null,
  price_includes_gst boolean not null default false,
  delivery_fee numeric(10,2) not null default 0,
  delivery_fee_type text not null default 'per_school_per_trip',  -- or 'per_trip'
  min_order_4_items integer not null default 0,
  min_order_5_items integer not null default 0,
  min_order_6_items integer not null default 0
);

-- Caterer contacts (can have multiple per caterer: primary + chef)
create table caterer_contacts (
  id uuid primary key default gen_random_uuid(),
  caterer_id uuid not null references caterers(id),
  name text not null,
  email text not null,
  role text not null,           -- 'primary' or 'chef'
  cc_on_orders boolean not null default false
);

-- Which caterer currently serves each school (and which could serve it)
create table caterer_school_coverage (
  id uuid primary key default gen_random_uuid(),
  caterer_id uuid not null references caterers(id),
  school_id uuid not null references schools(id),
  is_current boolean not null default false,  -- true = currently assigned, false = able to serve
  unique(caterer_id, school_id)
);

-- Menu items
create table menu_items (
  id uuid primary key default gen_random_uuid(),
  caterer_id uuid not null references caterers(id),
  name text not null,
  is_gf boolean not null default false,
  is_df boolean not null default false,
  is_nf boolean not null default false,
  is_vo boolean not null default false,   -- vegetarian option
  contains_pork boolean not null default false,
  contains_shellfish boolean not null default false,
  contains_beef boolean not null default false,
  contains_fish boolean not null default false,
  contains_red_meat boolean not null default false,
  unique(caterer_id, name)
);

-- Sessions (recurring weekly slots)
create table sessions (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references schools(id),
  caterer_id uuid not null references caterers(id),
  day_of_week text not null,   -- 'Monday', 'Tuesday', etc.
  start_time time not null,
  end_time time not null,
  dinner_time time not null,
  building text not null,
  default_manager_name text not null,
  default_manager_mobile text not null,
  year_levels integer[] not null  -- e.g. {9,10,11,12}
);

-- Students
create table students (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  year_level integer not null,
  student_email text,
  parent_name text,
  parent_email text,
  parent_mobile text,
  opted_out_of_catering boolean not null default false
);

-- Dietary restrictions (normalised; one row per restriction per student)
create table student_dietary (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id),
  restriction text not null,
  -- restriction values: halal, vegetarian, nut_free, gluten_free, dairy_free,
  --                     no_beef, no_pork, no_shellfish, no_fish, no_red_meat
  unique(student_id, restriction)
);

-- Which students are enrolled in which sessions (many-to-many)
create table enrollments (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id),
  session_id uuid not null references sessions(id),
  unique(student_id, session_id)
);

-- One-off session manager overrides (when the regular manager can't make it)
create table manager_overrides (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id),
  override_date date not null,
  manager_name text not null,
  manager_mobile text not null,
  unique(session_id, override_date)
);

-- One-off absences (specific student, specific session, specific date)
create table absences (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id),
  session_id uuid not null references sessions(id),
  absence_date date not null,
  unique(student_id, session_id, absence_date)
);

-- Session exclusions (school events that cancel or partially cancel a session)
create table session_exclusions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id),
  exclusion_date date not null,
  year_levels_excluded integer[],  -- null or empty = all year levels (full cancellation)
  reason text not null,
  unique(session_id, exclusion_date)
);

-- Weekly orders sent to caterers
create table weekly_orders (
  id uuid primary key default gen_random_uuid(),
  caterer_id uuid not null references caterers(id),
  week_start_date date not null,
  status text not null default 'draft',  -- draft, sent, confirmed, delivered
  email_subject text,
  email_body text,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  unique(caterer_id, week_start_date)
);

-- Which sessions each order covers, and meal count for that session
create table order_sessions (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references weekly_orders(id),
  session_id uuid not null references sessions(id),
  session_date date not null,
  meal_count integer not null,
  manager_name text not null,
  manager_mobile text not null
);

-- Line items: which menu items and how many, per session within an order
create table order_line_items (
  id uuid primary key default gen_random_uuid(),
  order_session_id uuid not null references order_sessions(id),
  menu_item_id uuid not null references menu_items(id),
  quantity integer not null check (quantity > 0)
);

-- Post-session feedback collected by on-site manager
create table feedback (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id),
  session_date date not null,
  menu_item_id uuid not null references menu_items(id),
  overall_rating integer check (overall_rating between 1 and 5),
  quality_rating integer check (quality_rating between 1 and 5),
  notes text,
  submitted_by text,
  created_at timestamptz not null default now()
);
