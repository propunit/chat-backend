from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from fastapi import WebSocket, WebSocketDisconnect
from schemas import ChatMessage
from chat_service import (
    get_or_create_conversation,
    save_message
)
from websocket import manager
from db import get_connection
from fcm import send_message_notification
from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.users import router as users_router
from routes.admin import router as admin_router
from routes.status import router as status_router

import os
os.makedirs("uploads/avatars", exist_ok=True)
os.makedirs("uploads/chat", exist_ok=True)
os.makedirs("uploads/status", exist_ok=True)

app = FastAPI(
    title="Chat Backend",
    version="1.0.0"
)

from migrate import run_migrations
run_migrations()

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(status_router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/online-users")
async def get_online_users():
    return {"online": manager.get_online_users()}


def _save_last_seen(user_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        conn.close()


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str
):
    conn = get_connection()
    user_id = None

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token=%s
                """,
                (token,)
            )
            row = cursor.fetchone()
            if not row:
                await websocket.close(code=1008)
                return
            user_id = str(row[0])

    finally:
        conn.close()

    await manager.connect(user_id, websocket)

    # Broadcast online status to all connected users
    for uid, ws in manager.connections.items():
        if uid != user_id:
            try:
                await ws.send_json({
                    "event": "user_online",
                    "user_id": user_id,
                })
            except:
                pass

    await websocket.send_json({"event": "welcome", "online": manager.get_online_users()})

    try:
        while True:
            data = await websocket.receive_json()

            event_type = data.get("event")

            if event_type == "typing":
                receiver_id = data.get("receiver_id")
                if receiver_id:
                    await manager.send_message(receiver_id, {
                        "event": "typing",
                        "sender_id": user_id,
                    })

            elif event_type == "stop_typing":
                receiver_id = data.get("receiver_id")
                if receiver_id:
                    await manager.send_message(receiver_id, {
                        "event": "stop_typing",
                        "sender_id": user_id,
                    })

            elif event_type == "reaction":
                message_id = data.get("message_id")
                emoji = data.get("emoji")
                receiver_id = data.get("receiver_id")
                if message_id and emoji:
                    import uuid as _uuid
                    react_conn = get_connection()
                    try:
                        with react_conn.cursor() as cursor:
                            cursor.execute(
                                """
                                INSERT INTO reactions (id, message_id, user_id, emoji)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (message_id, user_id)
                                DO UPDATE SET emoji = EXCLUDED.emoji
                                """,
                                (str(_uuid.uuid4()), message_id, user_id, emoji)
                            )
                        react_conn.commit()
                    finally:
                        react_conn.close()

                    payload = {
                        "event": "reaction",
                        "message_id": message_id,
                        "user_id": user_id,
                        "emoji": emoji,
                    }
                    if receiver_id:
                        await manager.send_message(receiver_id, payload)
                    await websocket.send_json(payload)

            elif event_type == "remove_reaction":
                message_id = data.get("message_id")
                receiver_id = data.get("receiver_id")
                if message_id:
                    react_conn = get_connection()
                    try:
                        with react_conn.cursor() as cursor:
                            cursor.execute(
                                "DELETE FROM reactions WHERE message_id = %s AND user_id = %s",
                                (message_id, user_id)
                            )
                        react_conn.commit()
                    finally:
                        react_conn.close()

                    payload = {
                        "event": "remove_reaction",
                        "message_id": message_id,
                        "user_id": user_id,
                    }
                    if receiver_id:
                        await manager.send_message(receiver_id, payload)
                    await websocket.send_json(payload)

            elif event_type == "delivered":
                message_id = data.get("message_id")
                sender_id = data.get("sender_id")
                if message_id and sender_id:
                    dlv_conn = get_connection()
                    try:
                        with dlv_conn.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE messages SET delivered_at = NOW()
                                WHERE id = %s AND delivered_at IS NULL
                                """,
                                (message_id,)
                            )
                        dlv_conn.commit()
                    finally:
                        dlv_conn.close()

                    await manager.send_message(sender_id, {
                        "event": "delivery_receipt",
                        "message_id": message_id,
                    })

            elif event_type == "read":
                sender_id = data.get("sender_id")
                if sender_id:
                    mark_conn = get_connection()
                    try:
                        with mark_conn.cursor() as cursor:
                            first, second = sorted([user_id, sender_id])
                            cursor.execute(
                                """
                                SELECT id FROM conversations
                                WHERE user1_id = %s AND user2_id = %s
                                """,
                                (first, second)
                            )
                            row = cursor.fetchone()
                            if row:
                                real_conv_id = str(row[0])
                                cursor.execute(
                                    """
                                    UPDATE messages SET read_at = NOW(), delivered_at = COALESCE(delivered_at, NOW())
                                    WHERE conversation_id = %s
                                    AND sender_id = %s
                                    AND read_at IS NULL
                                    """,
                                    (real_conv_id, sender_id)
                                )
                            mark_conn.commit()
                    finally:
                        mark_conn.close()

                    await manager.send_message(sender_id, {
                        "event": "read_receipt",
                        "reader_id": user_id,
                        "conversation_id": sender_id,
                    })

            elif event_type == "backup_status":
                receiver_id = data.get("receiver_id")
                if receiver_id:
                    await manager.send_message(receiver_id, {
                        "event": "backup_status",
                        "user_id": user_id,
                        "type": data.get("type"),
                        "status": data.get("status"),
                        "current": data.get("current", 0),
                        "total": data.get("total", 0),
                    })

            else:
                # Regular message
                message = ChatMessage(**data)

                conversation_id = get_or_create_conversation(
                    user_id,
                    message.receiver_id
                )

                saved = save_message(
                    conversation_id,
                    user_id,
                    message.type,
                    message.content,
                    reply_to_id=message.reply_to_id
                )

                payload = {
                    "id": saved["id"],
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "receiver_id": message.receiver_id,
                    "type": message.type,
                    "content": message.content,
                    "created_at": saved["created_at"],
                    "reply_to_id": message.reply_to_id,
                }

                if message.reply_to_id:
                    reply_conn = get_connection()
                    try:
                        with reply_conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT m.content, m.message_type, m.sender_id, u.display_name, u.username
                                FROM messages m JOIN users u ON u.id = m.sender_id
                                WHERE m.id = %s
                                """,
                                (message.reply_to_id,)
                            )
                            rrow = cur.fetchone()
                            if rrow:
                                payload["reply_to_content"] = rrow[0]
                                payload["reply_to_type"] = rrow[1]
                                payload["reply_to_sender_id"] = str(rrow[2])
                                payload["reply_to_sender_name"] = rrow[3] or rrow[4]
                    finally:
                        reply_conn.close()

                delivered = await manager.send_message(
                    message.receiver_id,
                    payload
                )

                if delivered:
                    dlv_conn2 = get_connection()
                    try:
                        with dlv_conn2.cursor() as cursor:
                            cursor.execute(
                                "UPDATE messages SET delivered_at = NOW() WHERE id = %s AND delivered_at IS NULL",
                                (saved["id"],)
                            )
                        dlv_conn2.commit()
                    finally:
                        dlv_conn2.close()
                else:
                    # Receiver offline — send FCM push notification
                    fcm_conn = get_connection()
                    try:
                        with fcm_conn.cursor() as cursor:
                            cursor.execute(
                                "SELECT fcm_token FROM users WHERE id = %s",
                                (message.receiver_id,)
                            )
                            row = cursor.fetchone()
                            if row and row[0]:
                                # Get sender name for notification
                                cursor.execute(
                                    "SELECT display_name, username FROM users WHERE id = %s",
                                    (user_id,)
                                )
                                sender_row = cursor.fetchone()
                                sender_name = sender_row[0] or sender_row[1] if sender_row else "Someone"
                                send_message_notification(
                                    fcm_token=row[0],
                                    sender_id=user_id,
                                    sender_name=sender_name,
                                    message_type=message.type,
                                    content=message.content,
                                )
                    finally:
                        fcm_conn.close()

                await websocket.send_json({
                    "status": "sent",
                    "message_id": saved["id"],
                    "delivered": delivered,
                })

                await websocket.send_json({
                    "event": "message_sent",
                    "data": payload
                })

    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(user_id)
            _save_last_seen(user_id)
            for uid, ws in manager.connections.items():
                try:
                    await ws.send_json({
                        "event": "user_offline",
                        "user_id": user_id,
                    })
                except:
                    pass

    except Exception as e:
        print(f"WebSocket error: {e}")
        if user_id:
            manager.disconnect(user_id)
            _save_last_seen(user_id)
            for uid, ws in manager.connections.items():
                try:
                    await ws.send_json({
                        "event": "user_offline",
                        "user_id": user_id,
                    })
                except:
                    pass


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
