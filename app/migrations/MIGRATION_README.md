# Migration Reset — Production Guide

## What changed

All previous migration files have been collapsed into a single **Init** revision with a
fixed, predictable ID: **`0001`**.

This makes it safe to reset the Alembic tracking state of a production database that
already has all tables in place, without touching any data.

---

## Fresh install (empty database)

```bash
flask db upgrade
```

This runs the `0001` migration and creates every table from scratch.

---

## Existing production database (data must be preserved)

The database already contains all the tables. You only need to tell Alembic which
revision it is at — **no DDL is executed**, your data is untouched.

### 1. Ensure the `alembic_version` table is empty (or doesn't exist yet)

```sql
-- SQLite
DELETE FROM alembic_version;

-- PostgreSQL / MySQL
TRUNCATE alembic_version;
```

If the table does not exist at all, `flask db stamp` will create it automatically.

### 2. Stamp the database as being at revision `0001`

```bash
flask db stamp 0001
```

### 3. Verify

```bash
flask db current
# Expected output:  0001 (head)
```

From this point on, `flask db upgrade` will be a no-op because the database is
already at `head`.

---

## Rationale

`flask db migrate -m "Init" --rev-id 0001` would generate a new file with
`revision = "0001"`. Using a fixed `--rev-id` means you always know what string
to stamp into `alembic_version` on the production server instead of hunting down
a random hex string.
