# INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
# CWE-89: SQL injection via string-formatted query.
import sqlite3


def find_account(db: sqlite3.Connection, user_id: str):
    cur = db.cursor()
    # User input concatenated directly into SQL — injectable.
    cur.execute(f"SELECT * FROM accounts WHERE owner = '{user_id}'")  # CWE-89
    return cur.fetchall()
