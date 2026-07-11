"""Run on startup to ensure all tables exist."""
from db import get_connection


def run_migrations():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            with open("schema.sql") as f:
                cur.execute(f.read())
            cur.execute("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id UUID DEFAULT NULL
            """)
            cur.execute("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ DEFAULT NULL
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS statuses (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    content_type VARCHAR(20) NOT NULL DEFAULT 'text',
                    content TEXT NOT NULL,
                    background_color VARCHAR(20) DEFAULT NULL,
                    media_url TEXT DEFAULT NULL,
                    caption TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS status_views (
                    id UUID PRIMARY KEY,
                    status_id UUID REFERENCES statuses(id) ON DELETE CASCADE,
                    viewer_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    viewed_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(status_id, viewer_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_statuses_user ON statuses(user_id, created_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_views_status ON status_views(status_id)
            """)
        conn.commit()
        print("Migrations complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
