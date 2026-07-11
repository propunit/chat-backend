"""Run this once to add read_at column to messages table."""
from db import get_connection

conn = get_connection()
try:
    with conn.cursor() as cursor:
        cursor.execute("""
            ALTER TABLE messages ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ DEFAULT NULL
        """)
    conn.commit()
    print("Migration complete: added read_at column to messages")
finally:
    conn.close()
