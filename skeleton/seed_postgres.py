"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python3 skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys
import secrets

import psycopg2
from psycopg2.extras import execute_values
from argon2 import PasswordHasher

ph = PasswordHasher()  # Argon2id — 用於 seed_users 的密碼雜湊

ph = PasswordHasher()

# ── Resolve Paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


# ── Seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    table = "metro_stations"
    columns = [
        "station_id", "name", "lines", "is_interchange_metro", 
        "interchange_metro_lines", "is_interchange_national_rail", 
        "interchange_national_rail_station_id", "adjacent_stations"
    ]
    rows = []
    for item in data:
        row = (
            item["station_id"],
            item["name"],
            item["lines"],
            item["is_interchange_metro"],
            item["interchange_metro_lines"],
            item["is_interchange_national_rail"],
            item["interchange_national_rail_station_id"],
            json.dumps(item["adjacent_stations"])
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    table = "national_rail_stations"
    columns = [
        "station_id", "name", "lines", "is_interchange_national_rail",
        "interchange_national_rail_lines", "is_interchange_metro",
        "interchange_metro_station_id", "adjacent_stations"
    ]
    rows = []
    for item in data:
        row = (
            item["station_id"],
            item["name"],
            item["lines"],
            item["is_interchange_national_rail"],
            item["interchange_national_rail_lines"],
            item["is_interchange_metro"],
            item["interchange_metro_station_id"],
            json.dumps(item["adjacent_stations"])
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    table = "metro_schedules"
    columns = [
        "schedule_id", "line", "direction", "origin_station_id",
        "destination_station_id", "first_train_time", "last_train_time",
        "travel_time_from_origin_min", "base_fare_usd",
        "per_stop_rate_usd", "frequency_min", "operates_on"
    ]
    rows = []
    stops_rows = []
    for item in data:
        rows.append((
            item["schedule_id"],
            item["line"],
            item["direction"],
            item["origin_station_id"],
            item["destination_station_id"],
            item["first_train_time"],
            item["last_train_time"],
            json.dumps(item["travel_time_from_origin_min"]),
            item["base_fare_usd"],
            item["per_stop_rate_usd"],
            item["frequency_min"],
            item["operates_on"]
        ))
        for order_idx, station_id in enumerate(item.get("stops_in_order", [])):
            stops_rows.append((item["schedule_id"], station_id, order_idx + 1))
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")
    if stops_rows:
        execute_values(
            cur,
            "INSERT INTO metro_schedule_stops (schedule_id, station_id, stop_order) VALUES %s ON CONFLICT DO NOTHING",
            stops_rows
        )
        print(f"  - Seeded {len(stops_rows)} rows into metro_schedule_stops")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    table = "national_rail_schedules"
    columns = [
        "schedule_id", "service_type", "direction",
        "origin_station_id", "destination_station_id",
        "first_train_time", "last_train_time",
        "travel_time_from_origin_min", "fare_classes",
        "frequency_min", "operates_on"
    ]
    rows = []
    stops_rows = []
    for item in data:
        rows.append((
            item["schedule_id"],
            item["service_type"],
            item["direction"],
            item["origin_station_id"],
            item["destination_station_id"],
            item["first_train_time"],
            item["last_train_time"],
            json.dumps(item["travel_time_from_origin_min"]),
            json.dumps(item["fare_classes"]),
            item["frequency_min"],
            item["operates_on"]
        ))
        for order_idx, station_id in enumerate(item.get("stops_in_order", [])):
            stops_rows.append((item["schedule_id"], station_id, order_idx + 1))
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")
    if stops_rows:
        execute_values(
            cur,
            "INSERT INTO rail_schedule_stops (schedule_id, station_id, stop_order) VALUES %s ON CONFLICT DO NOTHING",
            stops_rows
        )
        print(f"  - Seeded {len(stops_rows)} rows into rail_schedule_stops")

def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    table = "national_rail_seat_layouts"
    columns = ["layout_id", "schedule_id", "coaches"]
    rows = []
    for item in data:
        row = (
            item["layout_id"],
            item["schedule_id"],
            json.dumps(item["coaches"])
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")


def seed_users(cur):
    data = load("registered_users.json")

    # registered_users 主表不儲存密碼（schema 規定密碼隔離到 user_credentials）
    user_columns = [
        "user_id", "full_name", "email", "phone",
        "date_of_birth", "secret_question", "secret_answer",
        "registered_at", "is_active"
    ]
    user_rows = []
    cred_rows = []

    print("  - Hashing passwords with Argon2id (may take a moment)...")
    for item in data:
        user_rows.append((
            item["user_id"],
            item["full_name"],
            item["email"],
            item["phone"],
            item["date_of_birth"],
            item["secret_question"],
            item["secret_answer"],
            item["registered_at"],
            item["is_active"],
        ))
        # Argon2id 雜湊已內含 salt，dummy_salt 僅為滿足 NOT NULL 約束
        password_hash = ph.hash(item["password"])
        cred_rows.append((item["user_id"], password_hash, "argon2_internal"))

    inserted = insert_many(cur, "registered_users", user_columns, user_rows)
    print(f"  - Seeded {inserted} rows into registered_users")

    if cred_rows:
        execute_values(
            cur,
            "INSERT INTO user_credentials (user_id, password_hash, salt) VALUES %s ON CONFLICT DO NOTHING",
            cred_rows
        )
        print(f"  - Seeded {len(cred_rows)} rows into user_credentials")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    table = "bookings"
    columns = [
        "booking_id", "user_id", "schedule_id", "origin_station_id", 
        "destination_station_id", "travel_date", "departure_time", 
        "ticket_type", "fare_class", "coach", "seat_id", 
        "stops_travelled", "amount_usd", "status", "booked_at", "travelled_at"
    ]
    rows = []
    for item in data:
        row = (
            item["booking_id"], item["user_id"], item["schedule_id"], 
            item["origin_station_id"], item["destination_station_id"], 
            item["travel_date"], item["departure_time"], item["ticket_type"], 
            item["fare_class"], item["coach"], item["seat_id"], 
            item["stops_travelled"], item["amount_usd"], item["status"], 
            item["booked_at"], item["travelled_at"]
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    table = "metro_travel_history"
    columns = [
        "trip_id", "user_id", "schedule_id", "origin_station_id", 
        "destination_station_id", "travel_date", "ticket_type", 
        "day_pass_ref", "stops_travelled", "amount_usd", 
        "status", "purchased_at", "travelled_at"
    ]
    rows = []
    for item in data:
        row = (
            item["trip_id"], item["user_id"], item["schedule_id"],
            item["origin_station_id"], item["destination_station_id"],
            item["travel_date"], item["ticket_type"], 
            item.get("day_pass_ref"), item.get("stops_travelled"), 
            item["amount_usd"], item["status"], 
            item.get("purchased_at"), item.get("travelled_at")
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")


def seed_payments(cur):
    data = load("payments.json")
    table = "payments"
    columns = [
        "payment_id", "booking_id", "trip_id", "amount_usd",
        "method", "status", "paid_at"
    ]
    rows = []
    for item in data:
        raw_id = item["booking_id"]
        # MT 開頭是地鐵 trip，BK 開頭是國鐵 booking
        if raw_id.startswith("MT"):
            booking_id, trip_id = None, raw_id
        else:
            booking_id, trip_id = raw_id, None

        row = (
            item["payment_id"], booking_id, trip_id,
            item["amount_usd"], item["method"],
            item["status"], item["paid_at"]
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")

def seed_feedback(cur):
    data = load("feedback.json")
    table = "feedback"
    columns = ["feedback_id", "booking_id", "trip_id", "user_id", "rating", "comment", "submitted_at"]
    rows = []
    for item in data:
        raw_id = item["booking_id"]
        if raw_id.startswith("MT"):
            booking_id, trip_id = None, raw_id
        else:
            booking_id, trip_id = raw_id, None
        row = (
            item["feedback_id"],
            booking_id,
            trip_id,
            item["user_id"],
            item["rating"],
            item["comment"],
            item["submitted_at"]
        )
        rows.append(row)
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")
    
def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    # 關閉自動提交，改用手動嚴格 Transaction 控制
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 🔥 核心修正：告訴 PostgreSQL 這次 Transaction 內的所有外鍵約束「全部推遲檢查（DEFERRABLE）」
        # 這樣一來，在 commit 之前，資料庫不會因為互相參照的 NR01/MS01 還沒建好而噴錯崩潰！
        print("Enforcing transaction-level deferred constraints to bypass mutual master references...")
        cur.execute("SET CONSTRAINTS ALL DEFERRED;")

        print("Seeding Relational Infrastructure (Master Layer)...")
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        
        # ⚠️ ticket_types 必須在 bookings / metro_travel_history 之前完成（FK 依賴）
        # 不包 try/except：失敗直接 rollback，禁止靜默繼續
        print("Seeding Configurations & Core Business Policies...")
        types = load("ticket_types.json")
        for t in types:
            cfg_obj = json.dumps({"metro": t.get("metro"), "national_rail": t.get("national_rail")})
            cur.execute("""
                INSERT INTO ticket_types (ticket_type, display_name, available_on, description, config)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """, (t["ticket_type"], t["display_name"], t["available_on"], t["description"], cfg_obj))
        print("  - Seeded ticket_types")

        policies = load("refund_policy.json")
        for p in policies:
            if "compensation_rules" in p:
                for rule in p["compensation_rules"]:
                    cur.execute("""
                        INSERT INTO compensation_rules (rule_id, condition_desc, compensation, how_to_claim)
                        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """, (rule["rule_id"], rule["condition"], rule["compensation"], rule["how_to_claim"]))
                continue
            cur.execute("""
                INSERT INTO refund_policies (policy_id, label, applies_to, cancellation_windows, notes, no_show_policy)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """, (p["policy_id"], p["label"], json.dumps(p["applies_to"]), json.dumps(p["cancellation_windows"]), p.get("notes"), p.get("no_show_policy")))
        print("  - Seeded refund_policies and compensation_rules")

        rules = load("booking_rules.json")
        for k, c in [("national_rail", rules.get("national_rail")), ("metro", rules.get("metro")), ("general", rules.get("general_rules"))]:
            cur.execute("""
                INSERT INTO booking_rules (rule_key, config) VALUES (%s, %s)
                ON CONFLICT (rule_key) DO UPDATE SET config = EXCLUDED.config
            """, (k, json.dumps(c)))
        print("  - Seeded booking_rules")

        print("Seeding Timetables & Inventory...")
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        
        print("Seeding Users & Transaction Ledgers...")
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        
        # 4. 手動提交 Transaction，此時資料已全部就位，外鍵完整通過驗證！
        conn.commit()
        print("\n🎉 All done! Database seeded successfully into 3NF schema.")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Seeding process terminated due to error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()