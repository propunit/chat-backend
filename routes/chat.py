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
                    c.user1_id,
                    c.user2_id,
                    m.content AS last_message,
                    m.created_at AS last_message_at,
                    m.sender_id AS last_sender_id
                FROM conversations c
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
                (current_user["id"], current_user["id"])
            )

            rows = cursor.fetchall()

            conversations = []

            for row in rows:
                conv_id = str(row[0])
                user1_id = str(row[1])
                user2_id = str(row[2])

                peer_id = user2_id if user1_id == current_user["id"] else user1_id

                cursor.execute(
                    "SELECT display_name, username, profile_photo, last_seen, status FROM users WHERE id = %s",
                    (peer_id,)
                )
                peer_row = cursor.fetchone()
                peer_name = (peer_row[0] if peer_row[0] else peer_row[1]) if peer_row else "Unknown"
                peer_photo = peer_row[2] if peer_row else None
                peer_last_seen = peer_row[3].isoformat() if peer_row and peer_row[3] else None
                peer_status = (peer_row[4] or "") if peer_row else ""

                cursor.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE conversation_id = %s
                    AND sender_id = %s
                    AND read_at IS NULL
                    """,
                    (conv_id, peer_id)
                )
                unread_count = cursor.fetchone()[0]

                conversations.append({
                    "id": conv_id,
                    "peer_id": peer_id,
                    "peer_name": peer_name,
                    "peer_photo": peer_photo,
                    "peer_online": manager.is_online(peer_id),
                    "peer_last_seen": peer_last_seen,
                    "peer_status": peer_status,
                    "last_message": row[3],
                    "last_message_at": row[4].isoformat() if row[4] else None,
                    "last_sender_id": str(row[5]) if row[5] else None,
                    "unread_count": unread_count,
                })

            return conversations

    finally:
        conn.close()


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