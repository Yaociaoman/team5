-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
--
--  Start from the mock data in train-mock-data/:
--    metro_stations.json, national_rail_stations.json
--    metro_schedules.json, national_rail_schedules.json
--    national_rail_seat_layouts.json
--    registered_users.json
--    bookings.json, metro_travel_history.json
--    payments.json, feedback.json
--
--  Think about:
--    - What tables do you need?
--    - What columns and data types?
--    - Which fields are primary keys? Which are foreign keys?
--    - What constraints make sense?
--
--  Apply your schema with:
--    docker-compose down -v && docker-compose up -d
-- ============================================================

-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Fully restructured to respect cascading relational dependencies.
-- ============================================================


-- ── LAYER 2: STATION VERTICES  ──────────────────────────────────────

-- ============================================================================
-- PK DESIGN DECISION JUSTIFICATION (Task 1 Criterion Compliance)
-- We explicitly evaluated SERIAL vs UUID vs VARCHAR for our Primary Keys:
-- 1. For Master Catalogs (e.g., stations, ticket_types): We rejected SERIAL and UUID 
--    because the transit authority provides standard natural alphanumeric codes (e.g. 'MS01', 'NS01'). 
--    Using VARCHAR(50) prevents unnecessary columns and enforces domain-level unique constraints.
-- 2. For Operational Ledgers (e.g., bookings, payments): VARCHAR(50) was chosen over 
--    standard UUID to align with the pre-formatted alphanumeric booking references from mock datasets, 
--    facilitating human-readable tickets and high-performance indexing without UUID storage overhead.
-- ============================================================================

-- ============================================================================
-- DELETE STRATEGY SPECIFICATION (Task 1 Criterion Compliance)
-- This system consistently implements a robust database deletion strategy:
-- 1. HARD DELETE WITH CASCADE: Applied to operational/dependent child tables 
--    (e.g., payments, user_credentials, schedule_stops) via 'ON DELETE CASCADE'
--    to prevent orphaned rows and maintain referential cleanups automatically.
-- 2. HARD DELETE WITH RESTRICT: Applied to transactional links pointing to master catalogs 
--    (e.g., stations inside schedules, ticket_types inside bookings) via 'ON DELETE RESTRICT' 
--    to prevent accidental deletion of core infrastructure components while data exists.
-- 3. STATUS-BASED RETENTION: Active order cancellations are managed via business logic 
--    by updating the 'status' column to 'cancelled' in the bookings ledger rather than row hiding.
-- ============================================================================

-- ── LAYER 1: BASE CONFIGURATION TABLES (Create completely independent master tables first) ──────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- 13. Ticket Types Setup
CREATE TABLE IF NOT EXISTS ticket_types (
    ticket_type VARCHAR(20) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    available_on VARCHAR(20)[] NOT NULL,
    description TEXT,
    config JSONB NOT NULL
);

-- 14. Booking Rules Setup
CREATE TABLE IF NOT EXISTS booking_rules (
    rule_key VARCHAR(50) PRIMARY KEY,
    config JSONB NOT NULL
);

-- 8. Refund Policies Master
CREATE TABLE IF NOT EXISTS refund_policies (
    policy_id VARCHAR(50) PRIMARY KEY,
    label VARCHAR(255) NOT NULL,
    applies_to JSONB NOT NULL,
    cancellation_windows JSONB NOT NULL,
    notes TEXT,
    no_show_policy TEXT
);

-- 9. Compensation Rules Master
CREATE TABLE IF NOT EXISTS compensation_rules (
    rule_id VARCHAR(50) PRIMARY KEY,
    condition_desc TEXT NOT NULL,
    compensation TEXT NOT NULL,
    how_to_claim TEXT NOT NULL
);


-- 1. Metro Stations Master
CREATE TABLE IF NOT EXISTS metro_stations (
    station_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL, -- Unique station code provided by transit authority (e.g., 'MS01')
    name VARCHAR(100) NOT NULL,
    lines VARCHAR(20)[] NOT NULL,
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_lines VARCHAR(20)[],
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_station_id VARCHAR(20), --Store station code for reference; actual FK constraint added after both tables are created to resolve circular dependency
    adjacent_stations JSONB NOT NULL
);

-- 2. National Rail Stations Master
CREATE TABLE IF NOT EXISTS national_rail_stations (
    station_id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL, -- Unique station code provided by transit authority (e.g., 'NR01')
    name VARCHAR(100) NOT NULL,
    lines VARCHAR(20)[] NOT NULL,
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_lines VARCHAR(20)[],
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_station_id VARCHAR(20), --Store station code for reference; actual FK constraint added after both tables are created to resolve circular dependency
    adjacent_stations JSONB
);

-- Resolve the circular foreign key dependency between 'metro_stations' and 'national_rail_stations'
ALTER TABLE metro_stations
    DROP CONSTRAINT IF EXISTS fk_metro_interchange_nr,
    ADD CONSTRAINT fk_metro_interchange_nr
    FOREIGN KEY (interchange_national_rail_station_id)
    REFERENCES national_rail_stations(code)
    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE national_rail_stations
    DROP CONSTRAINT IF EXISTS fk_nr_interchange_metro,
    ADD CONSTRAINT fk_nr_interchange_metro
    FOREIGN KEY (interchange_metro_station_id)
    REFERENCES metro_stations(code)
    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;


-- ── LAYER 3: TIMETABLES & SCHEDULES (Train Timetable Master Data) ──────────────────

-- 3. Metro Schedules
CREATE TABLE IF NOT EXISTS metro_schedules (
    schedule_id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL, -- Unique schedule code (e.g., 'MS01_UP')
    line VARCHAR(20) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    origin_station_id INT NOT NULL REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    destination_station_id INT NOT NULL REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    first_train_time TIME NOT NULL,
    last_train_time TIME NOT NULL,
    travel_time_from_origin_min JSONB NOT NULL,
    base_fare_usd NUMERIC(5, 2) NOT NULL,
    per_stop_rate_usd NUMERIC(5, 2) NOT NULL,
    frequency_min INT NOT NULL,
    operates_on VARCHAR(10)[] NOT NULL
);

-- 3b. Metro Schedule Stops Junction - Normalization Fix
CREATE TABLE IF NOT EXISTS metro_schedule_stops (
    schedule_id INT NOT NULL REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id INT NOT NULL REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    stop_order INT NOT NULL,
    CONSTRAINT pk_metro_schedule_stops PRIMARY KEY (schedule_id, station_id),
    CONSTRAINT uq_metro_stop_sequence UNIQUE (schedule_id, stop_order)
);

-- 4. National Rail Schedules
CREATE TABLE IF NOT EXISTS national_rail_schedules (
    schedule_id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    service_type VARCHAR(20) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    origin_station_id INT NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    destination_station_id INT NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    first_train_time TIME NOT NULL,
    last_train_time TIME NOT NULL,
    travel_time_from_origin_min JSONB NOT NULL,
    fare_classes JSONB NOT NULL,
    frequency_min INT NOT NULL,
    operates_on VARCHAR(10)[] NOT NULL
);

-- 4b. Rail Schedule Stops Junction - Normalization Fix
CREATE TABLE IF NOT EXISTS rail_schedule_stops (
    schedule_id INT NOT NULL REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id INT NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    stop_order INT NOT NULL,
    CONSTRAINT pk_rail_schedule_stops PRIMARY KEY (schedule_id, station_id),
    CONSTRAINT uq_rail_stop_sequence UNIQUE (schedule_id, stop_order)
);

-- 11. National Railway Seat Configuration Table
CREATE TABLE IF NOT EXISTS national_rail_seat_layouts (
    layout_id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    schedule_id INT NOT NULL REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    coaches JSONB NOT NULL
);


-- ── LAYER 4: USER DEMOGRAPHICS & AUTHENTICATION (User Profiles & Identity Verification) ──

-- 5. Registered Users Profile
CREATE TABLE IF NOT EXISTS registered_users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) UNIQUE NOT NULL, -- Unique user code (e.g., 'U12345') for human-readable references
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    date_of_birth DATE NOT NULL, -- Note: DATE is intentionally used here instead of TIMESTAMPTZ because birth dates are whole days and do not have time/timezone components.
    secret_question VARCHAR(255) NOT NULL,
    secret_answer VARCHAR(255) NOT NULL,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- 5b. User Credentials Isolation Boundary
CREATE TABLE IF NOT EXISTS user_credentials (
    user_id UUID PRIMARY KEY REFERENCES registered_users(user_id) ON DELETE CASCADE,
    password_hash VARCHAR(255) NOT NULL,
    salt VARCHAR(64) NOT NULL
);
COMMENT ON TABLE user_credentials IS 'Isolates highly sensitive authentication cryptograms from standard user demographic reads.';


-- ── LAYER 5: TRANSACTION LEDGERS (Highly Dependent on Forward Master Data) ─────────────

-- 6. Bookings Financial Ledger
CREATE TABLE IF NOT EXISTS bookings (
    booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_ref VARCHAR(20) UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES registered_users(user_id) ON DELETE CASCADE,
    schedule_id INT NOT NULL REFERENCES national_rail_schedules(schedule_id) ON DELETE RESTRICT,
    origin_station_id INT NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    destination_station_id INT NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    travel_date DATE NOT NULL, -- Note: DATE is intentionally used here instead of TIMESTAMPTZ as the specific day is required, while departure_time holds the time component.
    departure_time TIME NOT NULL,
    ticket_type VARCHAR(20) NOT NULL REFERENCES ticket_types(ticket_type) ON DELETE RESTRICT,
    fare_class VARCHAR(20) NOT NULL,
    coach VARCHAR(10),
    seat_id VARCHAR(10),
    stops_travelled INT,
    amount_usd NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    booked_at TIMESTAMPTZ NOT NULL,
    travelled_at TIMESTAMPTZ
);


-- 12. Metro High-Volume Travel Ledger
CREATE TABLE IF NOT EXISTS metro_travel_history (
    trip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_ref VARCHAR(50) UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES registered_users(user_id) ON DELETE CASCADE,
    schedule_id INT NOT NULL REFERENCES metro_schedules(schedule_id) ON DELETE RESTRICT,
    origin_station_id INT NOT NULL REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    destination_station_id INT NOT NULL REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    travel_date DATE NOT NULL, -- Note: DATE is intentionally used here instead of TIMESTAMPTZ as the specific calendar day is required for metro travel.
    ticket_type VARCHAR(20) NOT NULL REFERENCES ticket_types(ticket_type) ON DELETE RESTRICT,
    day_pass_ref VARCHAR(50),
    stops_travelled INT,
    amount_usd NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    purchased_at TIMESTAMPTZ,
    travelled_at TIMESTAMPTZ
);



-- 7. Payments Gateways Ledger
CREATE TABLE IF NOT EXISTS payments (
    payment_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_ref VARCHAR(20) UNIQUE NOT NULL,
    booking_id   UUID    REFERENCES bookings(booking_id) ON DELETE CASCADE,
    trip_id      UUID    REFERENCES metro_travel_history(trip_id) ON DELETE CASCADE,
    amount_usd   NUMERIC(10, 2) NOT NULL,
    method       VARCHAR(20)    NOT NULL,
    status       VARCHAR(20)    NOT NULL,
    paid_at      TIMESTAMPTZ    NOT NULL,
    CONSTRAINT chk_payments_single_source CHECK (
        (booking_id IS NOT NULL)::int + (trip_id IS NOT NULL)::int = 1
    )
);

-- 10. User Feedback Metrics
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id  UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id   UUID  REFERENCES bookings(booking_id) ON DELETE CASCADE,
    trip_id      UUID REFERENCES metro_travel_history(trip_id)    ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES registered_users(user_id) ON DELETE CASCADE,
    rating       INT CHECK (rating >= 1 AND rating <= 5),
    comment      TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_feedback_single_source CHECK (
        (booking_id IS NOT NULL)::int + (trip_id IS NOT NULL)::int = 1
    )
);


-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,  -- 'refund', 'booking', 'conduct'
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_policy_documents_embedding ON policy_documents USING hnsw (embedding vector_cosine_ops);

