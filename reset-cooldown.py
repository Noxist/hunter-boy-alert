#!/usr/bin/env python3
"""Atomically clear the website's global cooldown without triggering HA."""
from pathlib import Path
import sqlite3

DB_PATH = Path("/home/leandro/service_data/hunter-boy-alert/cooldown.sqlite3")


def reset(db_path=DB_PATH):
    if not db_path.exists():
        return 0
    db = sqlite3.connect(db_path, timeout=20, isolation_level=None)
    try:
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activation'").fetchone()
        removed = db.execute("DELETE FROM activation WHERE id=1").rowcount if exists else 0
        db.execute("COMMIT")
        return removed
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset()
    print("Website cooldown reset. The button is available; no Home Assistant alert was sent.")
