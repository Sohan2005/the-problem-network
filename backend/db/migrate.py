"""
Safe runner for SQL migrations in backend/db/migrations/.

Dry run by default: connects read-only, prints the database name, current user and the statements
in the migration file, and changes nothing. Pass --apply to execute the file as one transaction.
Databases without a table named test_branch_marker are treated as production and also need --production.
Connection strings and host names are never printed.

Usage (from backend/):
    python db/migrate.py db/migrations/001_pipeline_state.sql
    python db/migrate.py db/migrations/001_pipeline_state.sql --apply                 # test branch only
    python db/migrate.py db/migrations/001_pipeline_state.sql --apply --production    # production
"""
import os
import re
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine

MARKER_TABLE = "test_branch_marker"


def split_statements(sql):
    """Split SQL into statements for display, respecting quotes, dollar-quoted blocks and -- comments."""
    statements = []
    current = []
    i = 0
    in_single = False
    dollar_tag = None
    while i < len(sql):
        ch = sql[i]
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                current.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
        elif in_single:
            if ch == "'":
                in_single = False
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
            continue
        elif ch == "'":
            in_single = True
        elif ch == "$":
            match = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                i += len(dollar_tag)
                continue
        elif ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def safe_error(exc):
    """First line of a database error, with anything that looks like a connection detail removed."""
    message = str(getattr(exc, "orig", exc)).strip().splitlines()
    message = message[0] if message else ""
    if re.search(r"@|host|neon\.tech|postgres(ql)?://|password", message, re.I):
        message = "[connection details redacted]"
    return f"{type(exc).__name__}: {message}"


def main():
    parser = argparse.ArgumentParser(description="Run a SQL migration file safely (dry run by default).")
    parser.add_argument("migration", help="Path to the .sql migration file")
    parser.add_argument("--apply", action="store_true", help="Execute the migration (default is a dry run)")
    parser.add_argument("--production", action="store_true",
                        help=f"Required with --apply when the database has no {MARKER_TABLE} table")
    args = parser.parse_args()

    if not os.path.isfile(args.migration) or not args.migration.endswith(".sql"):
        print(f"Migration file not found or not a .sql file: {args.migration}")
        return 2

    with open(args.migration, encoding="utf-8") as f:
        sql = f.read()
    statements = split_statements(sql)

    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            db_name, db_user, has_marker = conn.exec_driver_sql(
                "SELECT current_database(), current_user, to_regclass(%s) IS NOT NULL",
                (f"public.{MARKER_TABLE}",),
            ).one()
            conn.rollback()
    except Exception as exc:
        print("Could not connect or inspect the database:", safe_error(exc))
        return 1

    print(f"Database name: {db_name}")
    print(f"Current user:  {db_user}")
    print(f"Target:        {'TEST BRANCH (' + MARKER_TABLE + ' present)' if has_marker else 'PRODUCTION (no ' + MARKER_TABLE + ' table)'}")
    print(f"Migration:     {os.path.basename(args.migration)} ({len(statements)} statements)\n")

    for number, statement in enumerate(statements, 1):
        print(f"-- [{number}]")
        print(statement + ";\n")

    if not args.apply:
        print("Dry run only. Nothing was executed. Pass --apply to run this migration.")
        return 0

    if not has_marker and not args.production:
        print(f"Refusing to apply: this database has no {MARKER_TABLE} table, so it is treated as production.")
        print("Re-run with --apply --production if you really mean to migrate production.")
        return 3

    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        try:
            cursor.execute(sql)
        except Exception as exc:
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            print("Migration FAILED and was rolled back:", safe_error(exc))
            return 1
        finally:
            cursor.close()
    finally:
        raw.close()

    print(f"Migration applied: {os.path.basename(args.migration)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
