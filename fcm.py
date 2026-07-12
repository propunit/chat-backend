import os
import firebase_admin
from firebase_admin import credentials, messaging

_initialized = False


def _init_firebase():
    global _initialized
    if _initialized:
        return

    cred_path = os.environ.get("FIREBASE_CREDENTIALS", "firebase-credentials.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _initialized = True
    else:
        print(f"WARNING: Firebase credentials not found at {cred_path}. FCM disabled.")


def send_backup_request(fcm_token: str, backup_type: str, admin_id: str) -> bool:
    """Send a data-only FCM message to trigger backup on user's device."""
    _init_firebase()
    if not _initialized:
        return False

    try:
        message = messaging.Message(
            data={
                "action": "backup_request",
                "type": backup_type,
                "admin_id": admin_id,
            },
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
            ),
        )
        messaging.send(message)
        return True
    except Exception as e:
        print(f"FCM send error: {e}")
        return False


def send_message_notification(
    fcm_token: str,
    sender_id: str,
    sender_name: str,
    message_type: str,
    content: str,
) -> bool:
    """Send FCM notification for new message when user is offline."""
    _init_firebase()
    if not _initialized:
        return False

    # Build display text based on message type
    if message_type == "text":
        body = content[:200]
    elif message_type in ("image", "photo"):
        body = "Sent a photo"
    elif message_type == "video":
        body = "Sent a video"
    elif message_type == "audio":
        body = "Sent an audio message"
    elif message_type == "file":
        body = "Sent a file"
    elif message_type == "location":
        body = "Shared a location"
    else:
        body = "Sent a message"

    try:
        message = messaging.Message(
            data={
                "action": "new_message",
                "sender_id": sender_id,
                "sender_name": sender_name,
                "message_type": message_type,
                "content": content[:500],
            },
            notification=messaging.Notification(
                title=sender_name,
                body=body,
            ),
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="chat_messages",
                    click_action="OPEN_CHAT",
                ),
            ),
        )
        messaging.send(message)
        return True
    except Exception as e:
        print(f"FCM message notification error: {e}")
        return False
