# TransitFlow — Code Guidelines & Team Standards

This document defines the coding conventions, commenting standards, and team workflow rules
for the TransitFlow project. All team members are expected to follow these guidelines before
committing any code.

---

## Table of Contents

1. [File Ownership](#1-file-ownership)
2. [Git Workflow](#2-git-workflow)
3. [SQL / Schema Conventions](#3-sql--schema-conventions)
4. [Python Conventions](#4-python-conventions)
5. [Cypher / Neo4j Conventions](#5-cypher--neo4j-conventions)
6. [Comment Standards](#6-comment-standards)
7. [Database Reset Protocol](#7-database-reset-protocol)

---

## 1. File Ownership

Each file has a primary owner responsible for its correctness. Changes to another member's
file must be discussed first and reviewed before merging.

| File | Owner | Purpose |
|------|-------|---------|
| `databases/relational/schema.sql` | Schema lead | Table definitions, constraints, indexes |
| `databases/relational/queries.py` | Query lead | All PostgreSQL query and write functions |
| `skeleton/seed_postgres.py` | Seed lead | PostgreSQL data seeding |
| `databases/graph/seed.cypher` | Graph lead | Neo4j node and relationship definitions |
| `databases/graph/queries.py` | Graph lead | All Cypher query functions |
| `skeleton/seed_neo4j.py` | Graph lead | Neo4j seeding script |
| `train-mock-data/*.json` | Data lead | Source mock data files |

> Files inside `skeleton/` (agent.py, ui.py, llm_provider.py, config.py) are **read-only**
> unless the team has explicitly agreed to extend the agent or UI for Task 6.

---

## 2. Git Workflow

### Branch naming

```
feature/<short-description>     # new feature or function
fix/<short-description>         # bug fix
schema/<short-description>      # schema changes only
docs/<short-description>        # documentation updates
```

Examples:
```
feature/query-cheapest-route
fix/available-seats-fare-filter
schema/add-code-column-seat-layouts
docs/update-code-guidelines
```

### Commit messages

Use the format: `<type>: <what changed>`

| Type | When to use |
|------|-------------|
| `feat` | New function or table added |
| `fix` | Bug corrected |
| `schema` | schema.sql changed |
| `seed` | Seed script changed |
| `docs` | Documentation only |
| `refactor` | Code restructured, no behaviour change |

Examples:
```
feat: add query_interchange_path to graph queries
fix: correct hops=0 edge case in query_delay_ripple
schema: add code column to national_rail_seat_layouts
seed: fix station_map lookup in seed_metro_schedules
```

### Pull request rules

- At least one other team member must review before merging into `main`.
- If `schema.sql` changed, the reviewer must confirm they have reset and reseeded locally.
- Never force-push to `main`.

### What to commit / what not to commit

| Commit | Do not commit |
|--------|---------------|
| Everything inside `databases/` | `.env` (contains credentials) |
| `skeleton/seed_postgres.py` | `.venv/` folder |
| `skeleton/seed_neo4j.py` | Any `*.pyc` or `__pycache__/` |
| `train-mock-data/*.json` | Docker volume data or dump files |
| This file | Local test scripts not part of the project |

---

## 3. SQL / Schema Conventions

### Naming

- Table names: `snake_case`, plural noun — `metro_stations`, `national_rail_schedules`
- Column names: `snake_case` — `travel_date`, `fare_class`, `booked_at`
- Constraint names: prefix with type — `pk_`, `fk_`, `uq_`, `chk_`
  - Example: `pk_metro_schedule_stops`, `chk_payments_single_source`
- Index names: prefix `idx_` — `idx_policy_documents_embedding`

### Data types

| Data | Type | Never use |
|------|------|-----------|
| Fares, amounts | `NUMERIC(10, 2)` | `FLOAT`, `TEXT` |
| Timestamps with timezone | `TIMESTAMPTZ` | `TIMESTAMP`, `TEXT` |
| Calendar dates (no time) | `DATE` | `TIMESTAMPTZ` |
| Boolean flags | `BOOLEAN` | `INT`, `VARCHAR` |
| Passwords | argon2id hash string | Plain text, MD5, SHA |
| JSONB flexible config | `JSONB` | `TEXT` |

### Primary key rules

All PK choices must be justified with a comment directly on the PK column:

```sql
-- SERIAL for static reference/catalog tables
station_id SERIAL PRIMARY KEY, -- PK: SERIAL; static reference table, sequential INT minimises storage and optimises FK JOIN performance.

-- UUID for sensitive transactional tables
booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- PK: UUID; prevents sequential ID guessing on financial transaction records.

-- VARCHAR for domain-defined natural keys
ticket_type VARCHAR(20) PRIMARY KEY, -- PK: VARCHAR natural key; transit authority defines canonical codes (e.g. 'single', 'day_pass').
```

### Foreign key rules

Every FK must explicitly declare cascade behaviour — never leave it implicit:

```sql
-- Child tables that should be cleaned up with the parent
user_id UUID NOT NULL REFERENCES registered_users(user_id) ON DELETE CASCADE

-- References to master catalogs that must be protected
schedule_id INT NOT NULL REFERENCES national_rail_schedules(schedule_id) ON DELETE RESTRICT
```

### Delete strategy

This project uses **hard delete** as the primary strategy:

- `ON DELETE CASCADE`: child/operational tables (payments, credentials, schedule stops)
- `ON DELETE RESTRICT`: FK references pointing to master catalogs (stations, schedules, ticket types)
- **Status-based retention** for bookings only: cancellations set `status = 'cancelled'`; rows are never physically deleted to preserve financial audit trails.

This strategy must be documented in a block comment at the top of `schema.sql`.

---

## 4. Python Conventions

### Function naming

```python
query_*     # read-only SELECT functions (called by the agent)
execute_*   # write operations — INSERT, UPDATE (booking, cancellation)
seed_*      # data seeding functions in seed_postgres.py
_helper     # private helpers — prefix with underscore
```

### Return types

| Function type | Expected return |
|---------------|-----------------|
| `query_` single record | `dict` or `None` — never raise for missing row |
| `query_` multiple records | `list[dict]` — empty list `[]` if nothing found |
| `execute_` write operation | `tuple[bool, dict \| str]` — `(True, result)` or `(False, message)` |
| `seed_*` | `None` — print progress, raise on error |

### Transaction rules

`execute_booking` and `execute_cancellation` must:

1. Open a connection with `autocommit = False`
2. Wrap all inserts/updates in a single `conn.commit()`
3. Call `conn.rollback()` inside `except`
4. Always call `conn.close()` inside `finally`

```python
conn = psycopg2.connect(PG_DSN)
conn.autocommit = False
try:
    with conn.cursor(...) as cur:
        # all inserts here
        conn.commit()   # single commit covers everything
    return True, result
except Exception as e:
    conn.rollback()
    return False, str(e)
finally:
    conn.close()
```

Never commit the booking before inserting the payment — both must be in the same `conn.commit()`.

### Password hashing

All password operations must use argon2id via the `argon2-cffi` library:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()

# Hashing (register / update password)
hashed = _ph.hash(plain_text_password)

# Verifying (login)
try:
    _ph.verify(stored_hash, plain_text_password)
except VerifyMismatchError:
    return None  # wrong password
```

Plain text, MD5, and SHA passwords score 0 on the assessment regardless of other code quality.

### Idempotency in seed functions

Every `seed_*` function must be safe to re-run. Use `ON CONFLICT DO NOTHING`:

```python
execute_values(cur,
    "INSERT INTO metro_stations (...) VALUES %s ON CONFLICT DO NOTHING",
    rows
)
```

---

## 5. Cypher / Neo4j Conventions

### Node labels

| Network | Label | Example |
|---------|-------|---------|
| City metro | `MetroStation` | `MERGE (n:Station:MetroStation {station_id: 'MS01'})` |
| National rail | `NationalRailStation` | `MERGE (n:Station:NationalRailStation {station_id: 'NR01'})` |

> Note: the assessment rubric uses `NationalRailStation` — do not shorten to `RailStation`.

### Relationship types

| Type | Usage | Required property |
|------|-------|-------------------|
| `METRO_LINK` | Adjacent metro stations | `travel_time_min` |
| `RAIL_LINK` | Adjacent national rail stations | `travel_time_min` |
| `INTERCHANGE_TO` | Cross-network transfer points | `travel_time_min` |

### Idempotency

Always use `MERGE`, never `CREATE`, for nodes and relationships in seed scripts.
`CREATE` produces duplicates on every re-run; `MERGE` is safe:

```cypher
-- Correct
MERGE (n:MetroStation {station_id: $id})
SET n.name = $name

-- Wrong — creates a new node every re-run
CREATE (n:MetroStation {station_id: $id, name: $name})
```

### Query function return shape

Every graph query function must return one of:

```python
# Single path result
{
    "found": True,
    "path": [{"station_id": "MS01", "name": "Central Square"}, ...],
    "total_time_min": 14
}

# Multiple paths
[
    [{"from": "MS01", "to": "MS02", "line": "M1", "time_min": 3}, ...],
    ...
]

# Ripple / connections list
[
    {"station_id": "MS02", "name": "...", "hops_away": 1, "lines_affected": ["M1"]},
    ...
]
```

Always return an empty list `[]` or a `"found": False` dict — never raise an exception for missing paths.

---

## 6. Comment Standards

### When a comment is required

A comment is **required** (not optional) in these cases:

| Situation | Where |
|-----------|-------|
| PK type choice (SERIAL / UUID / VARCHAR) | Inline on the PK column in `schema.sql` |
| Delete strategy explanation | Block comment at top of `schema.sql` |
| Non-obvious SQL join or subquery | Inline above the relevant SQL line |
| Workaround for a known issue | Inline with explanation of why |
| Argon2id password hashing | Inline on `password_hash` column and hash call |

### Comment style

**SQL — block comment for design decisions:**
```sql
-- ============================================================
-- DELETE STRATEGY: Hard delete with CASCADE for child tables,
-- RESTRICT for master catalogs. Bookings use status-based
-- retention to preserve financial audit trails.
-- ============================================================
```

**SQL — inline comment for column rationale:**
```sql
travel_date DATE NOT NULL, -- DATE not TIMESTAMPTZ: only the calendar day is needed; departure_time holds the time component separately.
```

**Python — explain why, not what:**
```python
# Use a separate conn.commit() only after both booking and payment are inserted.
# If payment insert fails after booking commit, we'd have an orphaned booking
# with no payment record — violates atomicity requirement.
conn.commit()
```

**Python — do not just restate the code:**
```python
# Bad: insert the booking
cur.execute("INSERT INTO bookings ...")

# Good: booking insert must come before payment so booking_id FK is available
cur.execute("INSERT INTO bookings ...")
```

### Dead stubs

Every function must either be implemented or explicitly marked as not attempted:

```python
# Acceptable if not implemented
def query_something():
    raise NotImplementedError("query_something not yet implemented")

# Not acceptable — silent empty function
def query_something():
    pass
```

---

## 7. Database Reset Protocol

### When to reset

Reset your local database whenever any of these files changed in a `git pull`:

| Changed file | Action required |
|--------------|-----------------|
| `databases/relational/schema.sql` | Full reset (see below) |
| `skeleton/seed_postgres.py` | Re-run seed only |
| `databases/graph/seed.cypher` or `skeleton/seed_neo4j.py` | Re-run Neo4j seed |
| `train-mock-data/*.json` (policy files) | Re-run vector seed |

### Full reset sequence

```bash
# 1. Wipe all volumes and restart containers
docker compose down -v && docker compose up -d

# 2. Wait for containers to be healthy
docker compose ps

# 3. Seed PostgreSQL
python3 skeleton/seed_postgres.py

# 4. Seed Neo4j
python3 skeleton/seed_neo4j.py

# 5. Seed vectors (policy documents)
python3 skeleton/seed_vectors.py
```

### Before pushing a schema change

1. Reset your own database and confirm seeding completes without errors.
2. Notify the team in the group chat that `schema.sql` has changed.
3. All teammates must run the full reset sequence after pulling.