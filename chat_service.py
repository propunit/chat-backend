# import uuid
#
#
# def get_or_create_conversation(cursor, user1_id, user2_id):
#
#     first, second = sorted([user1_id, user2_id])
#
#     cursor.execute(
#         """
#         SELECT id
#         FROM conversations
#         WHERE user1_id=%s
#           AND user2_id=%s
#         """,
#         (first, second)
#     )
#
#     row = cursor.fetchone()
#
#     if row:
#         return row[0]
#
#     conversation_id = str(uuid.uuid4())
#
#     cursor.execute(
#         """
#         INSERT INTO conversations
#         (
#             id,
#             user1_id,
#             user2_id
#         )
#         VALUES
#         (%s,%s,%s)
#         """,
#         (
#             conversation_id,
#             first,
#             second
#         )
#     )
#
#     return conversation_id
#
#
# import uuid
#
#
# def save_message(
#     cursor,
#     conversation_id,
#     sender_id,
#     message_type,
#     content
# ):
#
#     message_id = str(uuid.uuid4())
#
#     cursor.execute(
#         """
#         INSERT INTO messages
#         (
#             id,
#             conversation_id,
#             sender_id,
#             message_type,
#             content
#         )
#         VALUES
#         (%s,%s,%s,%s,%s)
#         """,
#         (
#             message_id,
#             conversation_id,
#             sender_id,
#             message_type,
#             content
#         )
#     )
#
#     return message_id




import uuid

from db import get_connection


def get_or_create_conversation(user1_id: str, user2_id: str):

    first, second = sorted([user1_id, user2_id])

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM conversations
                WHERE user1_id=%s
                AND user2_id=%s
                """,
                (first, second)
            )

            row = cursor.fetchone()

            if row:
                return str(row[0])

            conversation_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO conversations
                (
                    id,
                    user1_id,
                    user2_id
                )
                VALUES
                (%s,%s,%s)
                """,
                (
                    conversation_id,
                    first,
                    second
                )
            )

            conn.commit()

            return conversation_id

    finally:
        conn.close()


def save_message(
    conversation_id: str,
    sender_id: str,
    message_type: str,
    content: str,
    reply_to_id: str = None
):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            message_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO messages
                (
                    id,
                    conversation_id,
                    sender_id,
                    message_type,
                    content,
                    reply_to_id
                )
                VALUES
                (%s,%s,%s,%s,%s,%s)
                RETURNING id, created_at
                """,
                (
                    message_id,
                    conversation_id,
                    sender_id,
                    message_type,
                    content,
                    reply_to_id
                )
            )

            row = cursor.fetchone()
            conn.commit()

            return {
                "id": str(row[0]),
                "created_at": row[1].isoformat()
            }

    finally:
        conn.close()