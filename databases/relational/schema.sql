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

-- 1. 捷運車站資料表
CREATE TABLE IF NOT EXISTS metro_stations (
    station_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines VARCHAR(20)[] NOT NULL,
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_lines VARCHAR(20)[],
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_station_id VARCHAR(50),
    adjacent_stations JSONB NOT NULL -- 儲存相鄰車站與時間的陣列
);

-- 2. 國鐵車站資料表
CREATE TABLE IF NOT EXISTS national_rail_stations (
    station_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines VARCHAR(20)[] NOT NULL,
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_lines VARCHAR(20)[],
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_station_id VARCHAR(50),
    adjacent_stations JSONB
);

-- 3. 捷運班次時刻表
CREATE TABLE IF NOT EXISTS metro_schedules (
    schedule_id VARCHAR(50) PRIMARY KEY,
    line VARCHAR(20) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(50) NOT NULL,
    destination_station_id VARCHAR(50) NOT NULL,
    stops_in_order VARCHAR(50)[] NOT NULL,
    first_train_time TIME NOT NULL,
    last_train_time TIME NOT NULL,
    travel_time_from_origin_min JSONB NOT NULL,
    base_fare_usd NUMERIC(5, 2) NOT NULL,
    per_stop_rate_usd NUMERIC(5, 2) NOT NULL,
    frequency_min INT NOT NULL,
    operates_on VARCHAR(10)[] NOT NULL
);

-- 4. 國鐵班次時刻表
CREATE TABLE IF NOT EXISTS national_rail_schedules (
    schedule_id VARCHAR(50) PRIMARY KEY,
    line VARCHAR(20) NOT NULL,
    service_type VARCHAR(20) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(50) NOT NULL,
    destination_station_id VARCHAR(50) NOT NULL,
    stops_in_order VARCHAR(50)[] NOT NULL,
    passed_through_stations VARCHAR(50)[], -- 特快車才有，允許 NULL
    first_train_time TIME NOT NULL,
    last_train_time TIME NOT NULL,
    travel_time_from_origin_min JSONB NOT NULL,
    fare_classes JSONB NOT NULL,            -- 包含標準和頭等艙票價
    frequency_min INT NOT NULL,
    operates_on VARCHAR(10)[] NOT NULL
);

-- 5. 使用者帳號資料表
CREATE TABLE IF NOT EXISTS registered_users (
    user_id VARCHAR(50) PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL, -- 電子郵件必須唯一
    password VARCHAR(255) NOT NULL,     -- 實務上應存 Hash，這裡依 Mock 資料存明文
    phone VARCHAR(20),
    date_of_birth DATE NOT NULL,
    secret_question VARCHAR(255) NOT NULL,
    secret_answer VARCHAR(255) NOT NULL,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- 6. 訂票資料表
CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES registered_users(user_id),
    schedule_id VARCHAR(50) NOT NULL REFERENCES national_rail_schedules(schedule_id),
    origin_station_id VARCHAR(50) NOT NULL,
    destination_station_id VARCHAR(50) NOT NULL,
    travel_date DATE NOT NULL,
    departure_time TIME NOT NULL,
    ticket_type VARCHAR(20) NOT NULL,
    fare_class VARCHAR(20) NOT NULL,
    coach VARCHAR(10),
    seat_id VARCHAR(10),
    stops_travelled INT,
    amount_usd NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    booked_at TIMESTAMPTZ NOT NULL,
    travelled_at TIMESTAMPTZ -- 可能為 NULL (例如已取消的訂單)
);

-- 7. 支付紀錄資料表
CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(50) PRIMARY KEY,
    booking_id VARCHAR(50) NOT NULL, -- 關聯到訂單或乘車紀錄
    amount_usd NUMERIC(10, 2) NOT NULL,
    method VARCHAR(20) NOT NULL,    -- credit_card, ewallet, debit_card
    status VARCHAR(20) NOT NULL,    -- paid, refunded
    paid_at TIMESTAMPTZ NOT NULL
);

-- 8. 退款政策主體表
CREATE TABLE IF NOT EXISTS refund_policies (
    policy_id VARCHAR(50) PRIMARY KEY,
    label VARCHAR(255) NOT NULL,
    applies_to JSONB NOT NULL,            -- 儲存 network_type, service_type 等過濾條件
    cancellation_windows JSONB NOT NULL,  -- 儲存完整的退款時間窗陣列
    notes TEXT,
    no_show_policy TEXT
);

-- 9. 延遲補償規則表 (獨立出來方便查詢)
CREATE TABLE IF NOT EXISTS compensation_rules (
    rule_id VARCHAR(50) PRIMARY KEY,
    condition_desc TEXT NOT NULL,
    compensation TEXT NOT NULL,
    how_to_claim TEXT NOT NULL
);

-- 10. 使用者回饋資料表
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id VARCHAR(50) PRIMARY KEY,
    booking_id VARCHAR(50) NOT NULL REFERENCES bookings(booking_id),
    user_id VARCHAR(50) NOT NULL REFERENCES registered_users(user_id),
    rating INT CHECK (rating >= 1 AND rating <= 5), -- 限制評分為 1-5 分
    comment TEXT,                                   -- 允許空值
    submitted_at TIMESTAMPTZ NOT NULL
);

-- 11. 國鐵座位配置資料表
CREATE TABLE IF NOT EXISTS national_rail_seat_layouts (
    layout_id VARCHAR(50) PRIMARY KEY,
    schedule_id VARCHAR(50) NOT NULL REFERENCES national_rail_schedules(schedule_id),
    coaches JSONB NOT NULL -- 儲存完整的車廂與座位配置資訊
);

-- 12. 捷運乘車紀錄表
CREATE TABLE IF NOT EXISTS metro_travel_history (
    trip_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES registered_users(user_id),
    schedule_id VARCHAR(50) NOT NULL REFERENCES metro_schedules(schedule_id),
    origin_station_id VARCHAR(50) NOT NULL,
    destination_station_id VARCHAR(50) NOT NULL,
    travel_date DATE NOT NULL,
    ticket_type VARCHAR(20) NOT NULL,
    day_pass_ref VARCHAR(50), -- 若為日票子行程，指向主日票 trip_id
    stops_travelled INT,
    amount_usd NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    purchased_at TIMESTAMPTZ,
    travelled_at TIMESTAMPTZ
);

-- 13. 票種設定資料表
CREATE TABLE IF NOT EXISTS ticket_types (
    ticket_type VARCHAR(20) PRIMARY KEY, -- 如 'single', 'return', 'day_pass'
    display_name VARCHAR(100) NOT NULL,
    available_on VARCHAR(20)[] NOT NULL,
    description TEXT,
    config JSONB NOT NULL -- 儲存詳細的 pricing_model, rules, validity 等設定
);

-- 14. 系統規則設定資料表
CREATE TABLE IF NOT EXISTS booking_rules (
    rule_key VARCHAR(50) PRIMARY KEY, -- 如 'national_rail', 'metro', 'general'
    config JSONB NOT NULL             -- 儲存該類別的所有規則設定
);


-- TODO: 接下來的其他資料表（國鐵車站、班次等）可以依序加在下方...

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
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);

