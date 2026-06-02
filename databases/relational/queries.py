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
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD

# Initialize PasswordHasher once
ph = PasswordHasher()



def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# TODO: Implement the query_ and execute_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.
    """
    default_response = []

    # Fixed parameter sequencing: passing travel_date as a structured condition parameter safely
    sql_query = """
        SELECT 
            nrs.schedule_id,
            nrs.line,
            nrs.service_type,
            nrs.direction,
            nrs.origin_station_id,
            nrs.destination_station_id,
            nrs.stops_in_order,
            nrs.first_train_time,
            nrs.last_train_time,
            nrs.travel_time_from_origin_min,
            nrs.fare_classes,
            nrs.frequency_min,
            nrs.operates_on,
            (
                SELECT COUNT(*)::INT 
                FROM bookings b 
                WHERE b.schedule_id = nrs.schedule_id 
                  AND b.travel_date = %s 
                  AND b.status = 'confirmed'
            ) AS booked_seats
        FROM national_rail_schedules nrs
        WHERE %s = ANY(nrs.stops_in_order)
          AND %s = ANY(nrs.stops_in_order)
          AND ARRAY_POSITION(nrs.stops_in_order, %s) < ARRAY_POSITION(nrs.stops_in_order, %s);
    """

    # If travel_date is None, fall back to an empty placeholder date string to keep SQL parameter count stable
    query_params = (
        travel_date if travel_date else "1970-01-01",
        origin_id,
        destination_id,
        origin_id,
        destination_id
    )

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, query_params)
                results = cur.fetchall()
                return [dict(row) for row in results]
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_national_rail_availability: {error}")
        return default_response


def query_national_rail_fare(schedule_id: str, fare_class: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the national rail fare for a single-ticket journey.
    """
    sql_query = """
        SELECT 
            fare_classes -> %s AS class_fare
        FROM national_rail_schedules
        WHERE schedule_id = %s;
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (fare_class, schedule_id))
                record = cur.fetchone()
                
                if not record or not record.get("class_fare"):
                    return None
                
                class_fare = record["class_fare"]
                # Psycopg2 automatically parses JSONB into a dictionary
                base_fare = float(class_fare.get("base_fare_usd", 0))
                per_stop_rate = float(class_fare.get("per_stop_rate_usd", 0))
                
                total_fare = base_fare + (per_stop_rate * stops_travelled)
                
                return {
                    "base_fare_usd": base_fare,
                    "per_stop_rate_usd": per_stop_rate,
                    "total_fare_usd": round(total_fare, 2)
                }
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_national_rail_fare: {error}")
        return None


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.
    """
    # Base fallback structure if an error occurs
    default_response = []

    # SQL query to locate rows where both station IDs exist inside the stops_in_order array,
    # utilizing ARRAY_POSITION to guarantee chronological route direction alignment.
    sql_query = """
        SELECT 
            schedule_id,
            line,
            direction,
            origin_station_id,
            destination_station_id,
            stops_in_order,
            first_train_time,
            last_train_time,
            travel_time_from_origin_min,
            base_fare_usd,
            per_stop_rate_usd,
            frequency_min,
            operates_on
        FROM metro_schedules
        WHERE %s = ANY(stops_in_order)
          AND %s = ANY(stops_in_order)
          AND ARRAY_POSITION(stops_in_order, %s) < ARRAY_POSITION(stops_in_order, %s);
    """

    query_params = (origin_id, destination_id, origin_id, destination_id)

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, query_params)
                results = cur.fetchall()
                
                # Convert RealDictRow footprints into explicit standard Python dict objects
                return [dict(row) for row in results]
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_metro_schedules: {error}")
        return default_response


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.
    """
    # SQL lookup targeting base pricing milestones directly from the relational attributes
    sql_query = """
        SELECT 
            base_fare_usd,
            per_stop_rate_usd
        FROM metro_schedules
        WHERE schedule_id = %s;
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (schedule_id,))
                record = cur.fetchone()
                
                # Guard clause against non-existent metro schedule entries
                if not record:
                    return None
                
                # Coerce data types explicitly to float structures for safe pricing calculations
                base_fare = float(record["base_fare_usd"])
                per_stop_rate = float(record["per_stop_rate_usd"])
                
                # Compute total fare metrics via the business pricing logic formulation
                total_fare = base_fare + (per_stop_rate * stops_travelled)
                
                return {
                    "base_fare_usd": base_fare,
                    "per_stop_rate_usd": per_stop_rate,
                    "total_fare_usd": round(total_fare, 2)
                }
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_metro_fare: {error}")
        return None


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date by unpacking
    the seat layout JSONB data and filtering out confirmed bookings.
    """
    # Base fallback array if query execution encounters issues
    default_response = []

    # SQL logic breakdown:
    # 1. Extract the specific fare_class array from the coaches JSONB block.
    # 2. Use JSONB expansion to flatten the unbooked seat roster into relational rows.
    # 3. Filter out rows matching seat_ids that already possess 'confirmed' bookings for that date.
    sql_query = """
        SELECT 
            seat.seat_id,
            seat.coach,
            seat.row AS row,
            seat.column AS column
        FROM national_rail_seat_layouts nrsl,
        JSONB_TO_RECORDSET(nrsl.coaches -> %s) AS seat(
            seat_id VARCHAR, 
            coach VARCHAR, 
            row VARCHAR, 
            column VARCHAR
        )
        WHERE nrsl.schedule_id = %s
          AND seat.seat_id NOT IN (
              SELECT COALESCE(seat_id, '')
              FROM bookings
              WHERE schedule_id = %s
                AND travel_date = %s
                AND status = 'confirmed'
          )
        ORDER BY seat.coach ASC, seat.row ASC, seat.column ASC;
    """

    # Pack the evaluation arguments sequentially into parameter tuples
    query_params = (fare_class, schedule_id, schedule_id, travel_date)

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, query_params)
                results = cur.fetchall()
                
                # Transform RealDictRow collection mappings back into clean standard Python dictionaries
                return [dict(row) for row in results]
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_available_seats: {error}")
        return default_response


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """
    Return a user's profile information by their registered unique email address.
    """
    # SQL query to match the user by email casing consistently
    sql_query = """
        SELECT 
            user_id,
            full_name,
            email,
            phone,
            date_of_birth,
            secret_question,
            secret_answer,
            registered_at,
            is_active
        FROM registered_users
        WHERE LOWER(email) = LOWER(%s);
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (user_email,))
                record = cur.fetchone()
                return dict(record) if record else None
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_user_profile: {error}")
        return None


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking and travel history separated by transit network type.
    """
    # Default envelope signature contract expected by the architecture layer
    default_response = {
        "national_rail": [],
        "metro": []
    }

    # SQL lookups to sequentially resolve user identification and histories
    get_user_id_sql = "SELECT user_id FROM registered_users WHERE LOWER(email) = LOWER(%s);"
    
    rail_sql = """
        SELECT 
            booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
            travel_date, departure_time, ticket_type, fare_class, coach, seat_id,
            stops_travelled, amount_usd, status, booked_at, travelled_at
        FROM bookings
        WHERE user_id = %s
        ORDER BY booked_at DESC;
    """

    metro_sql = """
        SELECT 
            trip_id, user_id, schedule_id, origin_station_id, destination_station_id,
            travel_date, ticket_type, day_pass_ref, stops_travelled, amount_usd,
            status, purchased_at, travelled_at
        FROM metro_travel_history
        WHERE user_id = %s
        ORDER BY purchased_at DESC;
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Step 1: Verify and fetch internal user_id
                cur.execute(get_user_id_sql, (user_email,))
                user_record = cur.fetchone()
                if not user_record:
                    return default_response
                
                user_id = user_record["user_id"]

                # Step 2: Query National Rail Bookings
                cur.execute(rail_sql, (user_id,))
                rail_bookings = cur.fetchall()

                # Step 3: Query Metro Travel Records
                cur.execute(metro_sql, (user_id,))
                metro_trips = cur.fetchall()

                return {
                    "national_rail": [dict(row) for row in rail_bookings],
                    "metro": [dict(row) for row in metro_trips]
                }
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_user_bookings: {error}")
        return default_response


def query_payment_info(booking_id: str) -> Optional[dict]:
    """
    Return the payment ledger transaction status corresponding to a target booking_id or trip_id.
    """
    # SQL query targeting polymorphic transaction record linkage identifiers
    sql_query = """
        SELECT 
            payment_id,
            booking_id,
            amount_usd,
            method,
            status,
            paid_at
        FROM payments
        WHERE booking_id = %s;
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (booking_id,))
                record = cur.fetchone()
                return dict(record) if record else None
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in query_payment_info: {error}")
        return None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking and associated payment records within a strict
    atomic transaction block using pessimistic concurrency locks.
    """
    # Establish standard database network link explicitly disabling autocommit
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Step 1: Manage auto-assignment if seat_id is specified as 'any'
            if seat_id == "any":
                # Fall back to previously verified read-only function to find vacant spots
                vacant_seats = query_available_seats(schedule_id, travel_date, fare_class)
                if not vacant_seats:
                    conn.rollback()
                    return False, "No seats available for this class"
                seat_id = vacant_seats[0]["seat_id"]

            # Step 2: Pessimistically lock and verify seat availability to prevent double-booking
            check_seat_sql = """
                SELECT booking_id 
                FROM bookings 
                WHERE schedule_id = %s 
                  AND travel_date = %s 
                  AND seat_id = %s 
                  AND status = 'confirmed'
                FOR UPDATE;
            """
            cur.execute(check_seat_sql, (schedule_id, travel_date, seat_id))
            if cur.fetchone():
                conn.rollback()
                return False, "Seat already occupied"

            # Step 3: Fetch schedule route details to calculate stops and pricing miles
            schedule_sql = """
                SELECT stops_in_order, first_train_time, service_type
                FROM national_rail_schedules 
                WHERE schedule_id = %s;
            """
            cur.execute(schedule_sql, (schedule_id,))
            schedule_record = cur.fetchone()
            if not schedule_record:
                conn.rollback()
                return False, "Target schedule not found"

            # Compute actual stops travelled using list indexing mechanics
            stops = schedule_record["stops_in_order"]
            try:
                stops_travelled = abs(stops.index(destination_station_id) - stops.index(origin_station_id))
            except ValueError:
                conn.rollback()
                return False, "Invalid origin or destination stations for this schedule"

            # Calculate fare metrics using the pre-built lookup function logic
            fare_info = query_national_rail_fare(schedule_id, fare_class, stops_travelled)
            if not fare_info:
                conn.rollback()
                return False, "Fare calculation configuration missing"
            
            amount_usd = fare_info["total_fare_usd"]

            # Step 4: Generate explicit primary keys and compile booking log payload
            new_booking_id = _gen_booking_id()
            new_payment_id = _gen_payment_id()
            now_timestamp = datetime.now(timezone.utc)

            insert_booking_sql = """
                INSERT INTO bookings (
                    booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                    travel_date, departure_time, ticket_type, fare_class, seat_id,
                    stops_travelled, amount_usd, status, booked_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', %s)
                RETURNING *;
            """
            booking_params = (
                new_booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                travel_date, schedule_record["first_train_time"], ticket_type, fare_class, seat_id,
                stops_travelled, amount_usd, now_timestamp
            )
            cur.execute(insert_booking_sql, booking_params)
            booking_record = cur.fetchone()

            # Step 5: Insert corresponding ledger records into payments table
            insert_payment_sql = """
                INSERT INTO payments (
                    payment_id, booking_id, amount_usd, method, status, paid_at
                ) VALUES (%s, %s, %s, 'credit_card', 'paid', %s);
            """
            cur.execute(insert_payment_sql, (new_payment_id, new_booking_id, amount_usd, now_timestamp))

            # Commit transactional batch changes safely to database storage
            conn.commit()
            return True, dict(booking_record)

    except Exception as e:
        conn.rollback()
        print(f"Transaction aborted inside execute_booking: {str(e)}")
        return False, str(e)
    finally:
        conn.close()


def execute_cancellation(
    booking_id: str, 
    user_id: str, 
    simulated_now: Optional[datetime] = None
) -> tuple[bool, dict | str]:
    """
    Cancel an active rail booking, computing exact cash refunds based on conditional
    cancellation windows parsed dynamically from service policy definitions.
    """
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Step 1: Lock and fetch valid targets matching confirmed records belonging to requested identity
            fetch_booking_sql = """
                SELECT b.*, s.service_type
                FROM bookings b
                JOIN national_rail_schedules s ON b.schedule_id = s.schedule_id
                WHERE b.booking_id = %s AND b.user_id = %s AND b.status = 'confirmed'
                FOR UPDATE;
            """
            cur.execute(fetch_booking_sql, (booking_id, user_id))
            booking = cur.fetchone()
            if not booking:
                conn.rollback()
                return False, "Booking record not found, unauthorized, or already processed"

            # Step 2: Formulate chronological timeframe calculation to evaluate policy rules
            # Combine travel_date and departure_time into a naive datetime, then localize or match offsets safely
            departure_datetime = datetime.combine(booking["travel_date"], booking["departure_time"])
            current_datetime = simulated_now if simulated_now else datetime.now() # Mock evaluation time metric tracking
            
            hours_until_departure = (departure_datetime - current_datetime).total_seconds() / 3600.0

            # Step 3: Match policy guidelines according to dynamic service_type signatures
            policy_id = "RF002" if booking["service_type"] == "Express" else "RF001"
            
            # Evaluate industry refund windows programmatically based on timing offsets
            refund_percentage = 0.0
            policy_note = "No refund available past window threshold markers."

            if policy_id == "RF001":  # Normal service windows
                if hours_until_departure >= 24.0:
                    refund_percentage = 1.00
                    policy_note = "Cancelled 24h+ prior to departure. 100% refund approved."
                elif hours_until_departure >= 12.0:
                    refund_percentage = 0.75
                    policy_note = "Cancelled 12h-24h prior to departure. 75% refund approved."
                elif hours_until_departure >= 2.0:
                    refund_percentage = 0.50
                    policy_note = "Cancelled 2h-12h prior to departure. 50% refund approved."
            else:  # Express service windows (RF002)
                if hours_until_departure >= 48.0:
                    refund_percentage = 1.00
                    policy_note = "Express Cancelled 48h+ prior to departure. 100% refund approved."
                elif hours_until_departure >= 6.0:
                    refund_percentage = 0.50
                    policy_note = "Express Cancelled 6h-48h prior to departure. 50% refund approved."

            refund_amount_usd = round(float(booking["amount_usd"]) * refund_percentage, 2)

            # Step 4: Update target records status fields concurrently
            update_booking_sql = "UPDATE bookings SET status = 'cancelled' WHERE booking_id = %s;"
            cur.execute(update_booking_sql, (booking_id,))

            # Step 5: Update polymorphic ledger records inside payments table
            update_payment_sql = """
                UPDATE payments 
                SET status = 'refunded', amount_usd = %s 
                WHERE booking_id = %s AND status = 'paid';
            """
            cur.execute(update_payment_sql, (refund_amount_usd, booking_id))

            conn.commit()
            return True, {
                "refund_amount_usd": refund_amount_usd,
                "policy_note": policy_note
            }

    except Exception as e:
        conn.rollback()
        print(f"Transaction aborted inside execute_cancellation: {str(e)}")
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
    """
    Register a new user inside a manual transactional block.
    Generates a unique user_id prefixing the 'RU' standard.
    """
    # Establish connection with autocommit disabled for safe data mutation
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Check if email is already registered to prevent duplication duplicates
            check_email_sql = "SELECT user_id FROM registered_users WHERE LOWER(email) = LOWER(%s);"
            cur.execute(check_email_sql, (email,))
            if cur.fetchone():
                conn.rollback()
                return False, "Email already registered"

            # Generate a new unique user_id sequence length tracker
            cur.execute("SELECT COUNT(*)::INT FROM registered_users;")
            user_count = cur.fetchone()["count"]
            new_user_id = f"RU{user_count + 1:02d}"

            # Format fields to map standard layout conventions
            full_name = f"{first_name} {surname}"
            date_of_birth = f"{year_of_birth}-01-01" # Default to Jan 1st for year placeholders
            
            # Hash the user's password using Argon2id before storing it
            hashed_password = ph.hash(password)

            # SQL query to insert the user profile data records
            insert_sql = """
                INSERT INTO registered_users (
                    user_id, full_name, email, date_of_birth, 
                    secret_question, secret_answer, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, TRUE);
            """
            cur.execute(insert_sql, (
                new_user_id, full_name, email, 
                date_of_birth, secret_question, secret_answer
            ))
            
            # Insert the hashed password into the user_credentials boundary
            cred_sql = """
                INSERT INTO user_credentials (user_id, password_hash, salt) 
                VALUES (%s, %s, %s);
            """
            # Argon2id handles its own salt in the hash string, but we fulfill the schema's NOT NULL constraint
            dummy_salt = "argon2_internal"
            cur.execute(cred_sql, (new_user_id, hashed_password, dummy_salt))
            
            conn.commit()
            return True, new_user_id

    except Exception as e:
        conn.rollback()
        print(f"Transaction aborted inside register_user: {str(e)}")
        return False, str(e)
    finally:
        conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials and return target active user profiles mapping contract layouts.
    """
    # SQL lookup targeting valid match records under full parameter containment constraints
    sql_query = """
        SELECT 
            ru.user_id,
            ru.email,
            ru.full_name,
            -- Split names dynamically on output to comply with downstream consumer mapping contracts
            SPLIT_PART(ru.full_name, ' ', 1) AS first_name,
            SPLIT_PART(ru.full_name, ' ', 2) AS surname,
            ru.phone,
            ru.date_of_birth,
            ru.is_active,
            uc.password_hash AS hashed_password
        FROM registered_users ru
        JOIN user_credentials uc ON ru.user_id = uc.user_id
        WHERE LOWER(ru.email) = LOWER(%s) 
          AND ru.is_active = TRUE;
    """

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (email,))
                record = cur.fetchone()
                
                if record:
                    hashed_password = record.pop("hashed_password")
                    try:
                        # Verify the password using Argon2id
                        ph.verify(hashed_password, password)
                        return dict(record)
                    except argon2_exceptions.VerifyMismatchError:
                        return None
                    except argon2_exceptions.InvalidHashError:
                        return None
                
                return None
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in login_user: {error}")
        return None


def get_user_secret_question(email: str) -> Optional[str]:
    """
    Return the secret security question assigned to a specific account profile.
    """
    sql_query = "SELECT secret_question FROM registered_users WHERE LOWER(email) = LOWER(%s);"

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (email,))
                record = cur.fetchone()
                return record["secret_question"] if record else None
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in get_user_secret_question: {error}")
        return None


def verify_secret_answer(email: str, answer: str) -> bool:
    """
    Verify security question responses matching target parameters case-insensitively.
    """
    sql_query = "SELECT secret_answer FROM registered_users WHERE LOWER(email) = LOWER(%s);"

    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_query, (email,))
                record = cur.fetchone()
                if not record:
                    return False
                
                # Enforce string evaluation lowercase validation check matches
                return record["secret_answer"].strip().lower() == answer.strip().lower()
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database error in verify_secret_answer: {error}")
        return False


def update_password(email: str, new_password: str) -> bool:
    """
    Update target password logs within safe serial atomic tracking scopes.
    """
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    
    # Hash the new password before updating
    hashed_password = ph.hash(new_password)

    sql_query = """
        UPDATE user_credentials 
        SET password_hash = %s 
        WHERE user_id = (
            SELECT user_id FROM registered_users WHERE LOWER(email) = LOWER(%s)
        );
    """

    try:
        with conn.cursor() as cur:
            cur.execute(sql_query, (hashed_password, email))
            # Check row count updates to confirm action mutation viability
            if cur.rowcount == 0:
                conn.rollback()
                return False
            
            conn.commit()
            return True
    except Exception as e:
        conn.rollback()
        print(f"Transaction aborted inside update_password: {str(e)}")
        return False
    finally:
        conn.close()


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
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
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
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