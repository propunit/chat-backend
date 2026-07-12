# app/dependencies.py

from datetime import datetime, timezone, timedelta

from fastapi import Header, HTTPException

from db import get_connection


def get_current_user(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header"
        )

    token = authorization.replace("Bearer ", "").strip()

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.username, s.expires_at, u.is_admin, u.display_name
                FROM sessions s
                JOIN users u
                    ON u.id = s.user_id
                WHERE s.token = %s
                """,
                (token,)
            )

            user = cursor.fetchone()

            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid session"
                )

            if user[2] < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=401,
                    detail="Session expired"
                )

            # Check if user is flagged/blocked
            cursor.execute("SELECT flagged FROM users WHERE id = %s", (str(user[0]),))
            flag_row = cursor.fetchone()
            if flag_row and flag_row[0]:
                raise HTTPException(
                    status_code=403,
                    detail="Your account has been blocked"
                )

            return {
                "id": str(user[0]),
                "username": user[1],
                "is_admin": user[3] if user[3] else False,
                "display_name": user[4] if len(user) > 4 else None,
            }

    finally:
        conn.close()