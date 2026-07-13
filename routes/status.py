import os
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, File, UploadFile, Form
from pydantic import BaseModel
from typing import Optional

from db import get_connection
from dependencies import get_current_user

UPLOAD_DIR = "uploads/status"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/status", tags=["status"])

EXPIRY_HOURS = 24


class TextStatusRequest(BaseModel):
    content: str
    background_color: Optional[str] = "#075E54"


@router.post("/create-text")
def create_text_status(
    body: TextStatusRequest,
    current_user=Depends(get_current_user),
):
    status_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO statuses (id, user_id, content_type, content, background_color)
                VALUES (%s, %s, 'text', %s, %s)
                RETURNING created_at
                """,
                (status_id, current_user["id"], body.content, body.background_color),
            )
            created_at = cur.fetchone()[0]
        conn.commit()
        return {
            "id": status_id,
            "content_type": "text",
            "content": body.content,
            "background_color": body.background_color,
            "created_at": created_at.isoformat(),
        }
    finally:
        conn.close()


@router.post("/create-media")
def create_media_status(
    file: UploadFile = File(...),
    caption: str = Form(""),
    current_user=Depends(get_current_user),
):
    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    unique_name = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)

    with open(filepath, "wb") as f:
        f.write(file.file.read())

    content_type = file.content_type or "application/octet-stream"
    if content_type.startswith("image/"):
        media_type = "image"
    elif content_type.startswith("video/"):
        media_type = "video"
    else:
        media_type = "image"

    media_url = f"/uploads/status/{unique_name}"
    status_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO statuses (id, user_id, content_type, content, media_url, caption)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING created_at
                """,
                (status_id, current_user["id"], media_type, caption, media_url, caption),
            )
            created_at = cur.fetchone()[0]
        conn.commit()
        return {
            "id": status_id,
            "content_type": media_type,
            "media_url": media_url,
            "caption": caption,
            "created_at": created_at.isoformat(),
        }
    finally:
        conn.close()


@router.get("/all")
def get_all_statuses(current_user=Depends(get_current_user)):
    conn = get_connection()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EXPIRY_HOURS)
    my_id = current_user["id"]
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, s.user_id, s.content_type, s.content, s.background_color,
                       s.media_url, s.caption, s.created_at,
                       u.display_name, u.username, u.profile_photo
                FROM statuses s
                JOIN users u ON u.id = s.user_id
                WHERE s.created_at > %s
                  AND (s.user_id = %s OR s.user_id IN (
                    SELECT CASE WHEN user1_id = %s THEN user2_id ELSE user1_id END
                    FROM conversations
                    WHERE user1_id = %s OR user2_id = %s
                  ))
                ORDER BY s.created_at DESC
                """,
                (cutoff, my_id, my_id, my_id, my_id),
            )
            rows = cur.fetchall()

            # Group by user
            users_map = {}
            for row in rows:
                uid = str(row[1])
                if uid not in users_map:
                    users_map[uid] = {
                        "user_id": uid,
                        "user_name": row[8] if row[8] else row[9],
                        "profile_photo": row[10],
                        "statuses": [],
                    }
                # Check if current user viewed this status
                cur.execute(
                    "SELECT 1 FROM status_views WHERE status_id = %s AND viewer_id = %s",
                    (str(row[0]), current_user["id"]),
                )
                viewed = cur.fetchone() is not None

                # Get view count
                cur.execute(
                    "SELECT COUNT(*) FROM status_views WHERE status_id = %s",
                    (str(row[0]),),
                )
                view_count = cur.fetchone()[0]

                users_map[uid]["statuses"].append({
                    "id": str(row[0]),
                    "content_type": row[2],
                    "content": row[3],
                    "background_color": row[4],
                    "media_url": row[5],
                    "caption": row[6],
                    "created_at": row[7].isoformat(),
                    "viewed": viewed,
                    "view_count": view_count,
                })

            # Separate my statuses from others
            my_statuses = users_map.pop(my_id, None)
            others = list(users_map.values())

            return {
                "my_statuses": my_statuses,
                "others": others,
            }
    finally:
        conn.close()


@router.post("/view/{status_id}")
def view_status(
    status_id: str,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO status_views (id, status_id, viewer_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (status_id, viewer_id) DO NOTHING
                """,
                (str(uuid.uuid4()), status_id, current_user["id"]),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.get("/viewers/{status_id}")
def get_status_viewers(
    status_id: str,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.display_name, u.profile_photo, sv.viewed_at
                FROM status_views sv
                JOIN users u ON u.id = sv.viewer_id
                WHERE sv.status_id = %s
                ORDER BY sv.viewed_at DESC
                """,
                (status_id,),
            )
            rows = cur.fetchall()
            viewers = []
            for row in rows:
                viewers.append({
                    "id": row[0],
                    "username": row[1],
                    "display_name": row[2],
                    "profile_photo": row[3],
                    "viewed_at": row[4].isoformat() if row[4] else None,
                })
            return {"viewers": viewers, "count": len(viewers)}
    finally:
        conn.close()


@router.delete("/{status_id}")
def delete_status(
    status_id: str,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM statuses WHERE id = %s AND user_id = %s",
                (status_id, current_user["id"]),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
