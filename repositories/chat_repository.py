from db import get_connection


def get_messages(user1_id: str, user2_id: str):

    first, second = sorted([user1_id, user2_id])

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    m.id,
                    m.sender_id,
                    c.user1_id,
                    c.user2_id,
                    m.message_type,
                    m.content,
                    m.created_at,
                    m.read_at,
                    m.reply_to_id,
                    rm.content AS reply_content,
                    rm.message_type AS reply_type,
                    rm.sender_id AS reply_sender_id,
                    COALESCE(ru.display_name, ru.username) AS reply_sender_name,
                    m.delivered_at
                FROM messages m
                JOIN conversations c
                    ON c.id = m.conversation_id
                LEFT JOIN messages rm ON rm.id = m.reply_to_id
                LEFT JOIN users ru ON ru.id = rm.sender_id
                WHERE c.user1_id=%s
                AND c.user2_id=%s
                ORDER BY m.created_at ASC
                """,
                (
                    first,
                    second
                )
            )

            rows = cursor.fetchall()

            messages = []

            for row in rows:

                sender_id = str(row[1])

                if sender_id == user1_id:
                    receiver_id = user2_id
                else:
                    receiver_id = user1_id

                msg_id = str(row[0])

                cursor.execute(
                    "SELECT user_id, emoji FROM reactions WHERE message_id = %s",
                    (msg_id,)
                )
                reaction_rows = cursor.fetchall()
                reactions = [{"user_id": str(r[0]), "emoji": r[1]} for r in reaction_rows]

                msg_data = {
                    "id": msg_id,
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "type": row[4],
                    "content": row[5],
                    "created_at": row[6].isoformat(),
                    "read_at": row[7].isoformat() if row[7] else None,
                    "reactions": reactions,
                    "reply_to_id": str(row[8]) if row[8] else None,
                    "reply_to_content": row[9],
                    "reply_to_type": row[10],
                    "reply_to_sender_id": str(row[11]) if row[11] else None,
                    "reply_to_sender_name": row[12],
                    "delivered_at": row[13].isoformat() if row[13] else None,
                }

                messages.append(msg_data)

            return messages

    finally:
        conn.close()
