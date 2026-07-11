from fastapi import APIRouter, Depends, HTTPException

from db import get_connection
from dependencies import get_current_user
from websocket import manager

router = APIRouter()


@router.get("/users")
def get_users(current_user=Depends(get_current_user)):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    username,
                    display_name,
                    profile_photo,
                    last_seen,
                    status
                FROM users
                WHERE id != %s
                ORDER BY username
                """,
                (current_user["id"],)
            )

            rows = cursor.fetchall()

            users = []

            for row in rows:
                uid = str(row[0])
                users.append({
                    "id": uid,
                    "username": row[1],
                    "display_name": row[2] if row[2] else row[1],
                    "profile_photo": row[3],
                    "is_online": manager.is_online(uid),
                    "last_seen": row[4].isoformat() if row[4] else None,
                    "status": row[5] or "",
                })

            return users

    finally:
        conn.close()


@router.get("/users/search")
def search_user(username: str, current_user=Depends(get_current_user)):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, username, display_name, profile_photo, last_seen, status
                FROM users
                WHERE username = %s
                AND id != %s
                """,
                (username, current_user["id"])
            )

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )

            uid = str(row[0])
            return {
                "id": uid,
                "username": row[1],
                "display_name": row[2] if row[2] else row[1],
                "profile_photo": row[3],
                "is_online": manager.is_online(uid),
                "last_seen": row[4].isoformat() if row[4] else None,
                "status": row[5] or "",
            }

    finally:
        conn.close()
