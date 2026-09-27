#!/usr/bin/env python3
"""Idempotent, dry-run-by-default backfill for secret platform settings."""

import argparse
import os
import sys

try:
    import psycopg2
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:
    raise SystemExit(f"required dependency missing: {exc}")

PREFIX = "gAAAAA"


def dsn_from_env() -> str:
    return "host={host} port={port} user={user} password={password} dbname={db}".format(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
        db=os.getenv("POSTGRES_DB", "unicorn_db"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", help="PostgreSQL DSN; defaults to POSTGRES_* environment")
    parser.add_argument("--commit", action="store_true", help="write changes; default is dry run")
    args = parser.parse_args()
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        parser.error("ENCRYPTION_KEY is not set")
    try:
        cipher = Fernet(key.encode())
    except Exception as exc:
        parser.error(f"invalid ENCRYPTION_KEY: {exc}")

    conn = psycopg2.connect(args.dsn or dsn_from_env())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value, is_secret FROM platform_settings ORDER BY key")
            migrated = already = skipped = unreadable = 0
            for name, value, is_secret in cur.fetchall():
                if not is_secret or value in (None, ""):
                    skipped += 1
                    continue
                if isinstance(value, bytes):
                    value = value.decode()
                if value.startswith(PREFIX):
                    try:
                        cipher.decrypt(value.encode())
                        already += 1
                    except InvalidToken:
                        unreadable += 1
                    continue
                encrypted = cipher.encrypt(value.encode()).decode()
                if cipher.decrypt(encrypted.encode()).decode() != value:
                    raise RuntimeError(f"round-trip verification failed for key={name}")
                if args.commit:
                    cur.execute("UPDATE platform_settings SET value = %s WHERE key = %s", (encrypted, name))
                migrated += 1
            if unreadable:
                raise RuntimeError(f"{unreadable} ciphertext row(s) cannot be read with ENCRYPTION_KEY")
        if args.commit:
            conn.commit()
        else:
            conn.rollback()
        print(f"{'COMMIT' if args.commit else 'DRY RUN'} migrated={migrated} already_encrypted={already} skipped={skipped}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
