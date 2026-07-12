import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile

from db import get_connection
from dependencies import get_current_user
from repositories.chat_repository import get_messages
from schemas import ChatMessage
from chat_service import get_or_create_conversation, save_message
from websocket import manager

CHAT_UPLOAD_DIR = "uploads/chat"
os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)

router = APIRouter()


@router.get("/messages/{receiver_id}")
def chat_history(
    receiver_id: str,
    current_user=Depends(get_current_user)
):

    messages = get_messages(
        current_user["id"],
        receiver_id
    )

    return {
        "messages": messages
    }


@router.post("/messages/send")
def send_message(
    message: ChatMessage,
    current_user=Depends(get_current_user)
):

    conversation_id = get_or_create_conversation(
        current_user["id"],
        message.receiver_id
    )

    saved = save_message(
        conversation_id,
        current_user["id"],
        message.type,
        message.content,
        reply_to_id=message.reply_to_id
    )

    return {
        "id": saved["id"],
        "conversation_id": conversation_id,
        "sender_id": current_user["id"],
        "receiver_id": message.receiver_id,
        "type": message.type,
        "content": message.content,
        "created_at": saved["created_at"],
        "reply_to_id": message.reply_to_id,
    }


@router.get("/conversations")
def get_conversations(current_user=Depends(get_current_user)):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    c.id,
                    CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END AS peer_id,
                    u.display_name,
                    u.username,
                    u.profile_photo,
                    u.last_seen,
                    u.status,
                    m.content AS last_message,
                    m.created_at AS last_message_at,
                    m.sender_id AS last_sender_id,
                    (SELECT COUNT(*) FROM messages um
                     WHERE um.conversation_id = c.id
                     AND um.sender_id = CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END
                     AND um.read_at IS NULL) AS unread_count
                FROM conversations c
                JOIN users u ON u.id = CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END
                JOIN LATERAL (
                    SELECT content, created_at, sender_id
                    FROM messages
                    WHERE conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) m ON true
                WHERE c.user1_id = %s OR c.user2_id = %s
                ORDER BY m.created_at DESC
                """,
                (current_user["id"], current_user["id"], current_user["id"],
                 current_user["id"], current_user["id"])
            )

            rows = cursor.fetchall()

            conversations = []

            for row in rows:
                peer_id = str(row[1])
                peer_name = (row[2] if row[2] else row[3]) or "Unknown"
                peer_photo = row[4]
                peer_last_seen = row[5].isoformat() if row[5] else None
                peer_status = (row[6] or "")

                conversations.append({
                    "id": str(row[0]),
                    "peer_id": peer_id,
                    "peer_name": peer_name,
                    "peer_photo": peer_photo,
                    "peer_online": manager.is_online(peer_id),
                    "peer_last_seen": peer_last_seen,
                    "peer_status": peer_status,
                    "last_message": row[7],
                    "last_message_at": row[8].isoformat() if row[8] else None,
                    "last_sender_id": str(row[9]) if row[9] else None,
                    "unread_count": row[10],
                })

            return conversations

    finally:
        conn.close()


@router.post("/messages/mark-read/{peer_id}")
async def mark_messages_read(
    peer_id: str,
    current_user=Depends(get_current_user)
):
    user_id = current_user["id"]
    first, second = sorted([user_id, peer_id])

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM conversations WHERE user1_id = %s AND user2_id = %s",
                (first, second)
            )
            row = cursor.fetchone()
            if row:
                conv_id = str(row[0])
                cursor.execute(
                    """
                    UPDATE messages SET read_at = NOW(), delivered_at = COALESCE(delivered_at, NOW())
                    WHERE conversation_id = %s
                    AND sender_id = %s
                    AND read_at IS NULL
                    """,
                    (conv_id, peer_id)
                )
            conn.commit()
    finally:
        conn.close()

    await manager.send_message(peer_id, {
        "event": "read_receipt",
        "reader_id": user_id,
        "conversation_id": peer_id,
    })

    return {"ok": True}


@router.post("/upload-file")
def upload_chat_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    unique_name = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(CHAT_UPLOAD_DIR, unique_name)

    with open(filepath, "wb") as f:
        f.write(file.file.read())

    content_type = file.content_type or "application/octet-stream"

    if content_type.startswith("image/"):
        file_type = "image"
    elif content_type.startswith("video/"):
        file_type = "video"
    elif content_type.startswith("audio/"):
        file_type = "audio"
    else:
        file_type = "file"

    file_url = f"/uploads/chat/{unique_name}"

    return {
        "file_url": file_url,
        "file_type": file_type,
        "file_name": file.filename,
        "content_type": content_type,
    }