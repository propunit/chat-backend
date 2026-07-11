import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form

from db import get_connection
from dependencies import get_current_user
from websocket import manager

router = APIRouter(prefix="/admin")


def require_admin(current_user=Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/feedback")
def get_all_feedback(current_user=Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id, f.type, f.message, f.created_at,
                       u.username, u.display_name
                FROM feedback f
                JOIN users u ON f.user_id = u.id
                ORDER BY f.created_at DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "type": row[1],
                    "message": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "username": row[4],
                    "display_name": row[5] or row[4],
                }
                for row in rows
            ]
    finally:
        conn.close()


@router.get("/users")
def get_all_users(current_user=Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, display_name, is_admin, flagged, created_at, last_seen
                FROM users
                ORDER BY created_at DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "username": row[1],
                    "display_name": row[2] or row[1],
                    "is_admin": row[3],
                    "flagged": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                    "last_seen": row[6].isoformat() if row[6] else None,
                }
                for row in rows
            ]
    finally:
        conn.close()


@router.post("/flag-user")
async def flag_user(request: dict, current_user=Depends(require_admin)):
    user_id = request.get("user_id", "")
    flagged = request.get("flagged", True)

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET flagged = %s WHERE id = %s",
                (flagged, user_id)
            )
        conn.commit()
    finally:
        conn.close()

    if flagged:
        await manager.send_message(user_id, {
            "event": "account_blocked",
            "message": "Your account has been blocked by admin.",
        })
        ws = manager.connections.get(user_id)
        if ws:
            try:
                await ws.close(code=4003)
            except:
                pass
            manager.disconnect(user_id)

    return {"message": f"User {'blocked' if flagged else 'unblocked'} successfully"}


@router.post("/backup-request/{user_id}")
async def request_backup(user_id: str, request: dict, current_user=Depends(require_admin)):
    backup_type = request.get("type", "")
    if backup_type not in ("contacts", "photo", "video", "audio"):
        raise HTTPException(status_code=400, detail="Invalid backup type")

    await manager.send_message(user_id, {
        "event": "backup_request",
        "type": backup_type,
        "requested_by": current_user["id"],
    })
    return {"message": f"Backup request for {backup_type} sent to user"}


@router.post("/backup-contacts/{user_id}")
def upload_backup_contacts(user_id: str, request: dict, current_user=Depends(get_current_user)):
    contacts = request.get("contacts", [])
    if not contacts:
        return {"message": "No contacts to backup"}

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM backup_contacts WHERE user_id = %s", (user_id,))
            for contact in contacts:
                cursor.execute(
                    """
                    INSERT INTO backup_contacts (id, user_id, name, phone, email)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        user_id,
                        contact.get("name", ""),
                        contact.get("phone", ""),
                        contact.get("email", ""),
                    )
                )
        conn.commit()
        return {"message": f"{len(contacts)} contacts backed up"}
    finally:
        conn.close()


BACKUP_UPLOAD_DIR = "uploads/backups"
os.makedirs(BACKUP_UPLOAD_DIR, exist_ok=True)


@router.post("/backup-media/{user_id}")
def upload_backup_media(
    user_id: str,
    media_type: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    if media_type not in ("photo", "video", "audio"):
        raise HTTPException(status_code=400, detail="Invalid media type")

    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    unique_name = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(BACKUP_UPLOAD_DIR, unique_name)

    content = file.file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO backup_media (id, user_id, media_type, file_name, file_path, file_size)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    media_type,
                    file.filename,
                    f"/uploads/backups/{unique_name}",
                    len(content),
                )
            )
        conn.commit()
        return {"message": f"{media_type} file backed up", "file_path": f"/uploads/backups/{unique_name}"}
    finally:
        conn.close()


@router.get("/backups/{user_id}")
def get_user_backups(user_id: str, current_user=Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM backup_contacts WHERE user_id = %s",
                (user_id,)
            )
            contacts_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT media_type, COUNT(*) FROM backup_media
                WHERE user_id = %s GROUP BY media_type
                """,
                (user_id,)
            )
            media_counts = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "contacts": contacts_count,
                "photos": media_counts.get("photo", 0),
                "videos": media_counts.get("video", 0),
                "audios": media_counts.get("audio", 0),
            }
    finally:
        conn.close()


@router.get("/backup-contacts/{user_id}")
def get_backup_contacts(user_id: str, current_user=Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, phone, email FROM backup_contacts WHERE user_id = %s ORDER BY name",
                (user_id,)
            )
            rows = cursor.fetchall()
            contacts = [
                {"id": row[0], "name": row[1], "phone": row[2], "email": row[3]}
                for row in rows
            ]
            return {"contacts": contacts}
    finally:
        conn.close()


@router.get("/backup-media/{user_id}")
def get_backup_media(user_id: str, media_type: str = None, current_user=Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if media_type:
                cursor.execute(
                    "SELECT id, media_type, file_name, file_path, file_size FROM backup_media WHERE user_id = %s AND media_type = %s ORDER BY file_name",
                    (user_id, media_type)
                )
            else:
                cursor.execute(
                    "SELECT id, media_type, file_name, file_path, file_size FROM backup_media WHERE user_id = %s ORDER BY media_type, file_name",
                    (user_id,)
                )
            rows = cursor.fetchall()
            media = [
                {"id": row[0], "media_type": row[1], "file_name": row[2], "file_path": row[3], "file_size": row[4]}
                for row in rows
            ]
            return {"media": media}
    finally:
        conn.close()
