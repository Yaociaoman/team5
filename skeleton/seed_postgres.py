"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python3 skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

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

import psycopg2
from psycopg2.extras import execute_values

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
    if not rows:
        return 0
    fields = ", ".join(columns)
    val_template = "(" + ", ".join(["%s"] * len(columns)) + ")"
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows, template=val_template)
    return cur.rowcount


# ── Seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    rows = [
        (                                             # station_id SERIAL
            s["station_id"],                                    # → code
            s["name"],
            s.get("lines", []),
            s.get("is_interchange_metro", False),
            s.get("interchange_metro_lines", []),
            s.get("is_interchange_national_rail", False),
            s.get("interchange_national_rail_station_id"),      # → interchange_national_rail_station_id
            json.dumps(s.get("adjacent_stations", [])),
        )
        for s in data
    ]
    inserted = insert_many(cur, "metro_stations", [
        "code", "name", "lines",
        "is_interchange_metro", "interchange_metro_lines",
        "is_interchange_national_rail", "interchange_national_rail_station_id",
        "adjacent_stations",
    ], rows)
    print(f"  - Seeded {inserted} rows into metro_stations")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    rows = [
        (                                          # station_id SERIAL
            s["station_id"],                                    # → code
            s["name"],
            s.get("lines", []),
            s.get("is_interchange_national_rail", False),
            s.get("interchange_national_rail_lines", []),
            s.get("is_interchange_metro", False),
            s.get("interchange_metro_station_id"),              # → interchange_metro_station_id
            json.dumps(s.get("adjacent_stations", [])),
        )
        for s in data
    ]
    inserted = insert_many(cur, "national_rail_stations", [
        "code", "name", "lines",
        "is_interchange_national_rail", "interchange_national_rail_lines",
        "is_interchange_metro", "interchange_metro_station_id",
        "adjacent_stations",
    ], rows)
    print(f"  - Seeded {inserted} rows into national_rail_stations")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    table = "metro_schedules"
    # stops_in_order 已從主表移除，改由 metro_schedule_stops junction table 儲存
    columns = [
        "schedule_id", "line", "direction", "origin_station_id",
        "destination_station_id", "first_train_time",
        "last_train_time", "travel_time_from_origin_min", "base_fare_usd",
        "per_stop_rate_usd", "frequency_min", "operates_on"
    ]
    # 加了"stops_in_order",
    rows = []
    stops_rows = []

    for item in data:
        # 查 origin/destination station_id (INT) by code
        cur.execute("SELECT station_id FROM metro_stations WHERE code = %s", (item["origin_station_id"],))
        orig = cur.fetchone()
        cur.execute("SELECT station_id FROM metro_stations WHERE code = %s", (item["destination_station_id"],))
        dest = cur.fetchone()
        if not orig or not dest:
            print(f"    ⚠ station not found for schedule {item['schedule_id']}, skipping")
            continue

        sched_rows.append((
            item["schedule_id"],                                # → code
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
        )
        rows.append(row)
        # Table 3b — 停靠順序正規化寫入 metro_schedule_stops
        for order_idx, station_id in enumerate(item["stops_in_order"]):
            stops_rows.append((item["schedule_id"], station_id, order_idx + 1))
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")
    if stops_rows:
        execute_values(cur,
            "INSERT INTO metro_schedule_stops (schedule_id, station_id, stop_order) VALUES %s ON CONFLICT DO NOTHING",
            stops_rows)
        print(f"  - Seeded {len(stops_rows)} rows into metro_schedule_stops")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    table = "national_rail_schedules"
    # line / stops_in_order / passed_through_stations 不存在於 schema，已移除
    # stops_in_order 改由 rail_schedule_stops junction table 儲存
    columns = [
        "schedule_id", "service_type", "direction",
        "origin_station_id", "destination_station_id",
        "first_train_time", "last_train_time",
        "travel_time_from_origin_min", "fare_classes",
        "frequency_min", "operates_on"
    ]
    # 加了"stops_in_order",
    rows = []
    stops_rows = []

    for item in data:
        row = (
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
        )
        rows.append(row)
        # Table 4b — 停靠順序正規化寫入 rail_schedule_stops
        for order_idx, station_id in enumerate(item["stops_in_order"]):
            stops_rows.append((item["schedule_id"], station_id, order_idx + 1))
    inserted = insert_many(cur, table, columns, rows)
    print(f"  - Seeded {inserted} rows into {table}")
    if stops_rows:
        execute_values(cur,
            "INSERT INTO rail_schedule_stops (schedule_id, station_id, stop_order) VALUES %s ON CONFLICT DO NOTHING",
            stops_rows)
        print(f"  - Seeded {len(stops_rows)} rows into rail_schedule_stops")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")

    for layout in data:
        # 查 schedule_id INT by code
        cur.execute("SELECT schedule_id FROM national_rail_schedules WHERE code = %s", (layout["schedule_id"],))
        sched = cur.fetchone()
        if not sched:
            print(f"    ⚠ schedule {layout['schedule_id']} not found, skipping seat layout")
            continue

        cur.execute("""
            INSERT INTO national_rail_seat_layouts (code, schedule_id, coaches)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO NOTHING
        """, (
            layout["schedule_id"],                              # → code
            sched[0],
            json.dumps(layout["coaches"]),
        ))

    print(f"  - Seeded seat layouts into national_rail_seat_layouts")


def seed_users(cur):
    data = load("registered_users.json")

    for u in data:
        full_name = u.get("full_name") or f"{u.get('first_name', '')} {u.get('surname', '')}".strip()
        cur.execute("""
            INSERT INTO registered_users
                (code, full_name, email, phone, date_of_birth,
                 secret_question, secret_answer, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
        """, (
            u["user_id"],                                       # → code
            full_name,
            u["email"],
            u.get("phone"),
            u.get("date_of_birth"),
            u.get("secret_question", ""),
            u.get("secret_answer", ""),
            u.get("is_active", True),
        ))

    print(f"  - Seeded {len(data)} rows into registered_users")

    # user_credentials: 查回 UUID 再 insert
    cred_count = 0
    for u in data:
        cur.execute("SELECT user_id FROM registered_users WHERE code = %s", (u["user_id"],))
        row = cur.fetchone()
        if not row:
            continue
        cur.execute("""
            INSERT INTO user_credentials (user_id, password_hash, salt)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            row[0],
            u.get("password", ""),                             # 教學用，存明文當 hash
            u.get("salt", "static_salt"),
        ))
        cred_count += 1
    print(f"  - Seeded {cred_count} rows into user_credentials")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    count = 0

    for b in data:
        # 查 user UUID
        cur.execute("SELECT user_id FROM registered_users WHERE code = %s", (b["user_id"],))
        user_row = cur.fetchone()
        if not user_row:
            print(f"    ⚠ user {b['user_id']} not found, skipping {b['booking_id']}")
            continue

        # 查 schedule INT
        cur.execute("SELECT schedule_id FROM national_rail_schedules WHERE code = %s", (b["schedule_id"],))
        sched_row = cur.fetchone()
        if not sched_row:
            print(f"    ⚠ schedule {b['schedule_id']} not found, skipping {b['booking_id']}")
            continue

        # 查 station INT
        cur.execute("SELECT station_id FROM national_rail_stations WHERE code = %s", (b["origin_station_id"],))
        orig_row = cur.fetchone()
        cur.execute("SELECT station_id FROM national_rail_stations WHERE code = %s", (b["destination_station_id"],))
        dest_row = cur.fetchone()
        if not orig_row or not dest_row:
            print(f"    ⚠ station not found, skipping {b['booking_id']}")
            continue

        cur.execute("""
            INSERT INTO bookings
                (booking_ref, user_id, schedule_id,
                 origin_station_id, destination_station_id,
                 travel_date, departure_time,
                 ticket_type, fare_class, coach, seat_id,
                 stops_travelled, amount_usd, status, booked_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (booking_ref) DO NOTHING
        """, (
            b["booking_id"],                                    # → booking_ref
            user_row[0],
            sched_row[0],
            orig_row[0],
            dest_row[0],
            b["travel_date"],
            b["departure_time"],
            b.get("ticket_type", "single"),
            b["fare_class"],
            b.get("coach"),
            b.get("seat_id"),
            b.get("stops_travelled"),
            b["amount_usd"],
            b.get("status", "confirmed"),
            b["booked_at"],
        ))
        count += 1

    print(f"  - Seeded {count} rows into bookings")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    count = 0

    for t in data:
        cur.execute("SELECT user_id FROM registered_users WHERE code = %s", (t["user_id"],))
        user_row = cur.fetchone()
        if not user_row:
            continue

        cur.execute("SELECT schedule_id FROM metro_schedules WHERE code = %s", (t["schedule_id"],))
        sched_row = cur.fetchone()
        if not sched_row:
            continue

        cur.execute("SELECT station_id FROM metro_stations WHERE code = %s", (t["origin_station_id"],))
        orig_row = cur.fetchone()
        cur.execute("SELECT station_id FROM metro_stations WHERE code = %s", (t["destination_station_id"],))
        dest_row = cur.fetchone()
        if not orig_row or not dest_row:
            continue

        cur.execute("""
            INSERT INTO metro_travel_history
                (trip_ref, user_id, schedule_id,
                 origin_station_id, destination_station_id,
                 travel_date, ticket_type, day_pass_ref,
                 stops_travelled, amount_usd, status,
                 purchased_at, travelled_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trip_ref) DO NOTHING
        """, (
            t["trip_id"],                                       # → trip_ref
            user_row[0],
            sched_row[0],
            orig_row[0],
            dest_row[0],
            t["travel_date"],
            t.get("ticket_type", "single"),
            t.get("day_pass_ref"),
            t.get("stops_travelled"),
            t.get("fare_usd") or t.get("amount_usd"),          # mock data 欄位名可能不同
            t.get("status", "completed"),
            t.get("purchased_at"),
            t.get("travelled_at"),
        ))
        count += 1

    print(f"  - Seeded {count} rows into metro_travel_history")


def seed_payments(cur):
    data = load("payments.json")
    count = 0

    for p in data:
        booking_uuid = None
        trip_uuid = None

        ref = p.get("booking_id") or p.get("trip_id")

        if ref:
            if ref.startswith("BK"):
                cur.execute("SELECT booking_id FROM bookings WHERE booking_ref = %s", (ref,))
                row = cur.fetchone()
                if row:
                    booking_uuid = row[0]

            elif ref.startswith("MT"):
                cur.execute("SELECT trip_id FROM metro_travel_history WHERE trip_ref = %s", (ref,))
                row = cur.fetchone()
                if row:
                    trip_uuid = row[0]

        if not booking_uuid and not trip_uuid:
            print(f"    ⚠ payment source {ref} not found, skipping {p['payment_id']}")
            continue

        cur.execute("""
            INSERT INTO payments
                (payment_ref, booking_id, trip_id,
                 amount_usd, method, status, paid_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (payment_ref) DO NOTHING
        """, (
            p["payment_id"],
            booking_uuid,
            trip_uuid,
            p["amount_usd"],
            p.get("payment_method") or p.get("method"),
            p.get("payment_status") or p.get("status"),
            p["paid_at"],
        ))

        count += 1

    print(f"  - Seeded {count} rows into payments")


def seed_feedback(cur):
    data = load("feedback.json")
    if not data:
        print("  - feedback: 0 rows (empty file)")
        return

    count = 0

    for f in data:
        cur.execute("SELECT user_id FROM registered_users WHERE code = %s", (f["user_id"],))
        user_row = cur.fetchone()
        if not user_row:
            continue

        booking_uuid = None
        trip_uuid = None

        ref = f.get("booking_id") or f.get("trip_id")

        if ref:
            if ref.startswith("BK"):
                cur.execute("SELECT booking_id FROM bookings WHERE booking_ref = %s", (ref,))
                row = cur.fetchone()
                if row:
                    booking_uuid = row[0]

            elif ref.startswith("MT"):
                cur.execute("SELECT trip_id FROM metro_travel_history WHERE trip_ref = %s", (ref,))
                row = cur.fetchone()
                if row:
                    trip_uuid = row[0]

        if not booking_uuid and not trip_uuid:
            print(f"    ⚠ feedback source {ref} not found, skipping")
            continue

        cur.execute("""
            INSERT INTO feedback
                (booking_id, trip_id, user_id, rating, comment, submitted_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            booking_uuid,
            trip_uuid,
            user_row[0],
            f.get("rating"),
            f.get("comment"),
            f["submitted_at"],
        ))

        count += 1

    print(f"  - Seeded {count} rows into feedback")

def seed_ticket_types(cur):
    rows = [
        ("single", "Single Ticket", ["metro", "national_rail"], "One-way ticket", json.dumps({})),
        ("return", "Return Ticket", ["national_rail"], "Round-trip ticket", json.dumps({})),
        ("day_pass", "Day Pass", ["metro"], "Unlimited metro travel for one day", json.dumps({})),
    ]

    inserted = insert_many(cur, "ticket_types", [
        "ticket_type", "display_name", "available_on", "description", "config"
    ], rows)

    print(f"  - Seeded {inserted} rows into ticket_types")

# ── Main Execution ───────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute("SET CONSTRAINTS ALL DEFERRED;")

        print("Seeding tables (dependency order):")
        seed_ticket_types(cur)
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        conn.commit()
        print("\nAll done. Database seeded successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\nSeeding process terminated due to error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()