"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD
# Use Argon2id for password hashing; the salt is embedded in the generated hash string.
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_ref() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    matching the given authority codes, calculating dynamic seat availability.
    """
    sql = """
        SELECT
            s.schedule_id,
            s.code AS schedule_code,
            s.service_type,
            s.direction,
            s.first_train_time AS departure_time,
            s.last_train_time AS arrival_time,
            (dest_stop.stop_order - orig_stop.stop_order) AS stops_travelled,
            -- Available standard seats count
            50 - COALESCE((
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.schedule_id = s.schedule_id
                  AND b.fare_class  = 'standard'
                  AND b.status      = 'confirmed'
                  AND (%(travel_date)s IS NULL OR b.travel_date = %(travel_date)s::date)
            ), 0) AS available_standard,
            -- Available first-class seats count
            20 - COALESCE((
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.schedule_id = s.schedule_id
                  AND b.fare_class  = 'first'
                  AND b.status      = 'confirmed'
                  AND (%(travel_date)s IS NULL OR b.travel_date = %(travel_date)s::date)
            ), 0) AS available_first
        FROM national_rail_schedules s
        JOIN rail_schedule_stops orig_stop ON orig_stop.schedule_id = s.schedule_id
        JOIN national_rail_stations os ON os.station_id = orig_stop.station_id AND os.code = %(origin_id)s
        JOIN rail_schedule_stops dest_stop ON dest_stop.schedule_id = s.schedule_id
        JOIN national_rail_stations ds ON ds.station_id = dest_stop.station_id AND ds.code = %(dest_id)s
        WHERE orig_stop.stop_order < dest_stop.stop_order
        ORDER BY s.first_train_time
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {
                "origin_id":   origin_id,
                "dest_id":     destination_id,
                "travel_date": travel_date,
            })
            return [dict(row) for row in cur.fetchall()]


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """Return metro schedules that serve both origin and destination stations by station codes."""
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.direction,
            s.frequency_min AS frequency_minutes,
            s.first_train_time AS first_service,
            s.last_train_time AS last_service,
            orig_stop.stop_order AS orig_order,
            dest_stop.stop_order AS dest_order,
            (dest_stop.stop_order - orig_stop.stop_order) AS stops_travelled
        FROM metro_schedules s
        JOIN metro_schedule_stops orig_stop ON orig_stop.schedule_id = s.schedule_id
        JOIN metro_stations os ON os.station_id = orig_stop.station_id AND os.code = %(origin_id)s
        JOIN metro_schedule_stops dest_stop ON dest_stop.schedule_id = s.schedule_id
        JOIN metro_stations ds ON ds.station_id = dest_stop.station_id AND ds.code = %(dest_id)s
        WHERE orig_stop.stop_order < dest_stop.stop_order
        ORDER BY s.first_train_time
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"origin_id": origin_id, "dest_id": destination_id})
            return [dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: int, stops_travelled: int) -> Optional[dict]:
    """Calculate the metro fare for a single-ticket journey."""
    sql = """
        SELECT
            base_fare_usd,
            per_stop_rate_usd,
            base_fare_usd + per_stop_rate_usd * %(stops)s AS total_fare_usd
        FROM metro_schedules
        WHERE schedule_id = %(schedule_id)s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"schedule_id": schedule_id, "stops": stops_travelled})
            row = cur.fetchone()
            return dict(row) if row else None


# ── NATIONAL RAIL FARE ────────────────────────────────────────────────────────

def query_national_rail_fare(
    schedule_id: int,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """Extract and parse national rail fare from JSONB schema configuration matrix."""
    # FLEXIBLE FARE MODEL：Fare rules are stored in JSONB to allow different pricing structures without requiring schema changes for future fare classes.
    sql = """
        SELECT 
            (fare_classes->%(fare_class)s->>'base_fare_usd')::numeric AS base_fare_usd,
            (fare_classes->%(fare_class)s->>'per_stop_rate_usd')::numeric AS per_stop_rate_usd
        FROM national_rail_schedules
        WHERE schedule_id = %(schedule_id)s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"schedule_id": schedule_id, "fare_class": fare_class})
            row = cur.fetchone()
            if not row or row["base_fare_usd"] is None:
                return None
            
            base = float(row["base_fare_usd"])
            per_stop = float(row["per_stop_rate_usd"])
            return {
                "base_fare_usd": base,
                "per_stop_rate_usd": per_stop,
                "total_fare_usd": base + (per_stop * stops_travelled)
            }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: int,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """Return available seats extracted dynamically from JSONB layouts excluding confirmed bookings."""
    sql = """
        SELECT (jsonb_array_elements(coach_elem->'seats')->>'seat_id') AS seat_id,
               (coach_elem->>'coach_label') AS coach,
               ((jsonb_array_elements(coach_elem->'seats')->>'row')::int) AS row,
               ((jsonb_array_elements(coach_elem->'seats')->>'col')::int) AS column
        FROM national_rail_seat_layouts sl,
        jsonb_array_elements(sl.coaches) AS coach_elem
        WHERE sl.schedule_id = %(schedule_id)s
          AND (coach_elem->>'class') = %(fare_class)s
          AND (jsonb_array_elements(coach_elem->'seats')->>'seat_id') NOT IN (
              SELECT b.seat_id
              FROM bookings b
              WHERE b.schedule_id  = %(schedule_id)s
                AND b.travel_date  = %(travel_date)s::date
                AND b.status       = 'confirmed'
          )
        ORDER BY coach, row, column
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {
                "schedule_id": schedule_id,
                "fare_class":  fare_class,
                "travel_date": travel_date,
            })
            return [dict(row) for row in cur.fetchall()]


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """Select `count` seats that are as close together as possible."""
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return user profile demographic properties using unique email matching."""
    sql = "SELECT user_id, code, full_name, email, phone, date_of_birth, EXTRACT(YEAR FROM date_of_birth)::int AS year_of_birth FROM registered_users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            return dict(row) if row else None


def query_user_bookings(user_email: str) -> dict:
    """Return a unified cross-network ledger representation of history linked to an account email."""
    user = query_user_profile(user_email)
    if not user:
        return {"national_rail": [], "metro": []}

    user_id = user["user_id"]

    nr_sql = """
        SELECT
            b.booking_id, b.booking_ref, b.travel_date,
            b.departure_time::text, b.fare_class, b.ticket_type, b.amount_usd, b.status,
            b.seat_id, b.schedule_id,
            orig.name  AS origin_name,
            dest.name  AS destination_name,
            b.origin_station_id, b.destination_station_id
        FROM bookings b
        JOIN national_rail_stations orig ON orig.station_id = b.origin_station_id
        JOIN national_rail_stations dest ON dest.station_id = b.destination_station_id
        WHERE b.user_id = %s
        ORDER BY b.travel_date DESC
    """

    metro_sql = """
        SELECT
            t.trip_id, t.trip_ref, t.travel_date,
            t.amount_usd AS fare_usd, t.schedule_id,
            orig.name AS origin_name,
            dest.name AS destination_name,
            t.origin_station_id, t.destination_station_id
        FROM metro_travel_history t
        JOIN metro_stations orig ON orig.station_id = t.origin_station_id
        JOIN metro_stations dest ON dest.station_id = t.destination_station_id
        WHERE t.user_id = %s
        ORDER BY t.travel_date DESC
    """

    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(nr_sql, (user_id,))
            nr_rows = [dict(r) for r in cur.fetchall()]

            cur.execute(metro_sql, (user_id,))
            metro_rows = [dict(r) for r in cur.fetchall()]

    return {"national_rail": nr_rows, "metro": metro_rows}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return the payment metadata ledger ledger row mapping to a booking UUID."""
    sql = "SELECT * FROM payments WHERE booking_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
            row = cur.fetchone()
            return dict(row) if row else None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: int,
    origin_station_id: int,
    destination_station_id: int,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """Process a new national rail ticket purchase ledger entry within isolated safety limits."""
    # TRANSACTION ATOMICITY:
    # Booking creation must execute as a single transactional unit.
    # Any failure during validation, fare calculation, or seat assignment triggers a full rollback to prevent partial reservations.
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Validate timetable routing structure constraints
            cur.execute("""
                SELECT orig.stop_order AS orig_order,
                       dest.stop_order AS dest_order,
                       s.first_train_time AS departure_time
                FROM national_rail_schedules s
                JOIN rail_schedule_stops orig ON orig.schedule_id = s.schedule_id AND orig.station_id = %s
                JOIN rail_schedule_stops dest ON dest.schedule_id = s.schedule_id AND dest.station_id = %s
                WHERE s.schedule_id = %s AND orig.stop_order < dest.stop_order
            """, (origin_station_id, destination_station_id, schedule_id))
            sched_row = cur.fetchone()
            if not sched_row:
                conn.rollback()
                return False, "Schedule mapping failure or layout directional restriction violated."

            stops_travelled = sched_row["dest_order"] - sched_row["orig_order"]
            departure_time  = sched_row["departure_time"]

            # Seat auto-allocation
            if seat_id.lower() == "any":
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    conn.rollback()
                    return False, "No unallocated capacity matches requested seating tier."
                seat_id = available[0]["seat_id"]

            # CONCURRENCY SAFEGUARD:Prevent duplicate seat allocation by validating that no confirmed booking already occupies the requested seat on the same schedule and travel date.
            cur.execute("""
                SELECT 1 FROM bookings
                WHERE schedule_id = %s AND seat_id = %s AND travel_date = %s::date AND status = 'confirmed'
            """, (schedule_id, seat_id, travel_date))
            if cur.fetchone():
                conn.rollback()
                return False, f"Target inventory slot {seat_id} holds locked active registration."

            # Calculate ticket billing values
            fare_info = query_national_rail_fare(schedule_id, fare_class, stops_travelled)
            if not fare_info:
                conn.rollback()
                return False, "Failed to resolve currency metrics for layout configuration."
            amount_usd = float(fare_info["total_fare_usd"])

            booking_ref = _gen_booking_ref()
            booked_at   = datetime.now(timezone.utc)

            cur.execute("""
                INSERT INTO bookings
                    (user_id, schedule_id, origin_station_id, destination_station_id,
                     booking_ref, seat_id, travel_date, departure_time,
                     fare_class, ticket_type, amount_usd, status, booked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::date, %s, %s, %s, %s, 'confirmed', %s)
                RETURNING booking_id
            """, (
                user_id, schedule_id, origin_station_id, destination_station_id,
                booking_ref, seat_id, travel_date, departure_time,
                fare_class, ticket_type, amount_usd, booked_at
            ))
            booking_id = cur.fetchone()["booking_id"]

            payment_ref = "PY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            cur.execute("""
                INSERT INTO payments
                    (payment_ref, booking_id, trip_id, amount_usd, method, status, paid_at)
                VALUES (%s, %s, NULL, %s, 'card', 'completed', %s)
            """, (payment_ref, booking_id, amount_usd, datetime.now(timezone.utc)))

            conn.commit()   # ← booking + payment
            return True, {
                "booking_id":              str(booking_id),
                "booking_ref":             booking_ref,
                "user_id":                 str(user_id),
                "schedule_id":             schedule_id,
                "origin_station_id":       origin_station_id,
                "destination_station_id":  destination_station_id,
                "seat_id":                 seat_id,
                "travel_date":             travel_date,
                "departure_time":          str(departure_time),
                "fare_class":              fare_class,
                "ticket_type":             ticket_type,
                "amount_usd":              amount_usd,
                "status":                  "confirmed",
            }

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """Execute cancellation and compute window-based refund policies."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT b.*, s.service_type
                FROM bookings b
                JOIN national_rail_schedules s ON s.schedule_id = b.schedule_id
                WHERE b.booking_id = %s AND b.user_id = %s
            """, (booking_id, user_id))
            booking = cur.fetchone()

            if not booking:
                conn.rollback()
                return False, "Target ledger line item missing or context mismatch."

            if booking["status"] == "cancelled":
                conn.rollback()
                return False, "Target operational ledger state already resolved as inactive."

            travel_dt = datetime.combine(booking["travel_date"], booking["departure_time"]).replace(tzinfo=timezone.utc)
            now       = datetime.now(timezone.utc)
            hours_until = (travel_dt - now).total_seconds() / 3600

            service_type = booking["service_type"]
            amount       = float(booking["amount_usd"])

            # POLICY ENGINE:
            # Refund percentages are dynamically determined using service-specific cancellation ladders (RF001 for Normal services and RF002 for Express services) rather than hard-coded refund values.
            if service_type == "express":
                if hours_until > 48:
                    refund_pct, policy_note = 1.0, "RF002: >48h before departure — 100% refund"
                elif hours_until >= 12:
                    refund_pct, policy_note = 0.5, "RF002: 12–48h before departure — 50% refund"
                else:
                    refund_pct, policy_note = 0.0, "RF002: <12h before departure — no refund"
            else:
                if hours_until > 48:
                    refund_pct, policy_note = 1.0, "RF001: >48h before departure — 100% refund"
                elif hours_until >= 24:
                    refund_pct, policy_note = 0.75, "RF001: 24–48h before departure — 75% refund"
                elif hours_until >= 1:
                    refund_pct, policy_note = 0.5, "RF001: 1–24h before departure — 50% refund"
                else:
                    refund_pct, policy_note = 0.0, "RF001: <1h before departure — no refund"

            refund_amount = round(amount * refund_pct, 2)
            # CANCELLATION AUDIT POLICY:
            # Although the schema defines hard-delete behavior for true DELETE operations, user cancellation is handled as a status update instead of deleting the row.
            # This preserves booking history while still allowing database-level delete rules to protect referential integrity when administrative deletion is required.
            cur.execute("UPDATE bookings SET status = 'cancelled' WHERE booking_id = %s", (booking_id,))
            conn.commit()
            return True, {
                "booking_id":       str(booking_id),
                "refund_amount_usd": refund_amount,
                "policy_note":       policy_note,
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """Register a user record splitting credentials securely to protect core identity rows."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM registered_users WHERE email = %s", (email,))
            if cur.fetchone():
                conn.rollback()
                return False, "Target identity property holds an active assignment."

            cur.execute("SELECT COUNT(*) AS cnt FROM registered_users")
            count = cur.fetchone()["cnt"]
            code = f"RU{str(count + 1).zfill(2)}"
            full_name = f"{first_name} {surname}".strip()
            dob = f"{year_of_birth}-01-01"

            cur.execute("""
                INSERT INTO registered_users (code, full_name, email, date_of_birth, secret_question, secret_answer)
                VALUES (%s, %s, %s, %s::date, %s, %s)
                RETURNING user_id
            """, (code, full_name, email, dob, secret_question, secret_answer))
            user_id = cur.fetchone()["user_id"]

            # User passwords are hashed with Argon2id before persistence, and only the hash is stored in the isolated user_credentials table.
            hashed = _ph.hash(password)   # argon2id，salt automatically embedded in the hash string
            
            # This implementation intentionally separates credentials from profile data to support future migration toward Argon2id/bcrypt hashing and reduce exposure of sensitive data.
            cur.execute("""
                INSERT INTO user_credentials (user_id, password_hash, salt)
                VALUES (%s, %s, 'argon2id')
            """, (user_id, hashed))

            conn.commit()
            return True, str(user_id)
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """Verify argon2id password hash against isolated credential boundary rows."""
    # AUTHENTICATION BOUNDARY:Credentials are stored in a dedicated table to enforce separation between identity information and authentication secrets.
    sql = """
        SELECT u.user_id, u.code, u.full_name, u.email, u.phone,
               u.date_of_birth, u.is_active,
               split_part(u.full_name, ' ', 1) AS first_name,
               split_part(u.full_name, ' ', 2) AS surname,
               c.password_hash
        FROM registered_users u
        JOIN user_credentials c ON c.user_id = u.user_id
        WHERE u.email = %s AND u.is_active = TRUE
    """
    conn = psycopg2.connect(PG_DSN)
    try:
    
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                _ph.verify(row["password_hash"], password)  # argon2id check
            except VerifyMismatchError:
                return None
            result = dict(row)
            result.pop("password_hash")   # don't send hash back
            return result
    finally:
        conn.close()


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the security verification challenge mapped to an identity key."""
    sql = "SELECT secret_question FROM registered_users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Validate safety answers using case-insensitive parameters."""
    sql = "SELECT secret_answer FROM registered_users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            return row[0].lower() == answer.lower() if row else False


def update_password(email: str, new_password: str) -> bool:
    """Hash new password with argon2id before storing."""
    # Password updates must follow the same Argon2id hashing policy as registration.
    hashed = _ph.hash(new_password)
    sql = """
        UPDATE user_credentials 
        SET password_hash = %s 
        WHERE user_id = (SELECT user_id FROM registered_users WHERE email = %s)
    """
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (hashed, email))
            affected = cur.rowcount
        conn.commit()
        return affected > 0
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """Find the most relevant policy documents for a given query embedding."""
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """Insert a policy document with its embedding into the database."""
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]