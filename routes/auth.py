import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
import bcrypt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from db import get_connection
from schemas import LoginRequest, RegisterRequest, ChangePasswordRequest, ChangeDisplayNameRequest
from dependencies import get_current_user

GOOGLE_WEB_CLIENT_ID = "343091332306-ng4j4mnokn94u0vra07su8d8r886scbt.apps.googleusercontent.com"

UPLOAD_DIR = "uploads/avatars"

router = APIRouter()

SESSION_DAYS = 30

@router.post("/register", status_code=201)
def register(request: RegisterRequest):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            # Check if username already exists
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE username = %s
                """,
                (request.username,)
            )

            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="Username already exists"
                )

            # Hash password
            password_hash = bcrypt.hashpw(
                request.password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

            # Insert user
            display_name = request.display_name.strip() if request.display_name else request.username
            cursor.execute(
                """
                INSERT INTO users
                (id, username, display_name, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    request.username,
                    display_name,
                    password_hash,
                )
            )

        conn.commit()

        return {
            "message": "User registered successfully"
        }

    finally:
        conn.close()


@router.post("/login")
def login(request: LoginRequest):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, password_hash, display_name, profile_photo, status, is_admin
                FROM users
                WHERE username=%s
                """,
                (request.username,)
            )

            user = cursor.fetchone()

            if user is None:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )

            user_id, password_hash, display_name, profile_photo, status, is_admin = user

            if not bcrypt.checkpw(
                    request.password.encode("utf-8"),
                    password_hash.encode("utf-8")
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )

            # Check if user is flagged/blocked
            cursor.execute("SELECT flagged FROM users WHERE id = %s", (user_id,))
            flag_row = cursor.fetchone()
            if flag_row and flag_row[0]:
                raise HTTPException(
                    status_code=403,
                    detail="Your account has been blocked. Contact admin."
                )

            token = str(uuid.uuid4())

            expires_at = datetime.utcnow() + timedelta(days=SESSION_DAYS)

            cursor.execute(
                """
                INSERT INTO sessions
                (
                    token,
                    user_id,
                    expires_at
                )
                VALUES
                (%s,%s,%s)
                """,
                (
                    token,
                    user_id,
                    expires_at
                )
            )

            cursor.execute(
                "UPDATE users SET last_seen = NOW() WHERE id = %s",
                (user_id,)
            )

        conn.commit()

        return {
            "token": token,
            "user_id": str(user_id),
            "username": request.username,
            "display_name": display_name or request.username,
            "profile_photo": profile_photo,
            "status": status or "",
            "is_admin": is_admin or False,
        }

    finally:
        conn.close()


@router.post("/google-login")
def google_login(request: dict):
    token = request.get("id_token", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="id_token is required")

    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_WEB_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_email = idinfo.get("email", "")
    google_name = idinfo.get("name", "")
    google_picture = idinfo.get("picture", "")

    if not google_email:
        raise HTTPException(status_code=400, detail="Email not available from Google")

    username = google_email.split("@")[0]

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, display_name, profile_photo, status, is_admin, flagged FROM users WHERE username = %s",
                (username,)
            )
            user = cursor.fetchone()

            if user:
                user_id, display_name, profile_photo, status, is_admin, flagged = user
                if flagged:
                    raise HTTPException(status_code=403, detail="Your account has been blocked. Contact admin.")
            else:
                user_id = str(uuid.uuid4())
                display_name = google_name or username
                profile_photo = google_picture or None
                status = ""
                is_admin = False
                password_hash = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt()).decode()
                cursor.execute(
                    "INSERT INTO users (id, username, display_name, password_hash, profile_photo) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, username, display_name, password_hash, profile_photo)
                )

            token_val = str(uuid.uuid4())
            expires_at = datetime.utcnow() + timedelta(days=SESSION_DAYS)
            cursor.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_val, user_id, expires_at)
            )
            cursor.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (user_id,))

        conn.commit()

        return {
            "token": token_val,
            "user_id": str(user_id),
            "username": username,
            "display_name": display_name or username,
            "profile_photo": profile_photo,
            "status": status or "",
            "is_admin": is_admin or False,
        }
    finally:
        conn.close()


@router.post("/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user=Depends(get_current_user)
):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT password_hash
                FROM users
                WHERE id = %s
                """,
                (current_user["id"],)
            )

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )

            if not bcrypt.checkpw(
                request.current_password.encode("utf-8"),
                row[0].encode("utf-8")
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Current password is incorrect"
                )

            new_hash = bcrypt.hashpw(
                request.new_password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (new_hash, current_user["id"])
            )

        conn.commit()

        return {
            "message": "Password changed successfully"
        }

    finally:
        conn.close()


@router.post("/change-display-name")
def change_display_name(
    request: ChangeDisplayNameRequest,
    current_user=Depends(get_current_user)
):

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE users
                SET display_name = %s
                WHERE id = %s
                """,
                (request.display_name.strip(), current_user["id"])
            )

        conn.commit()

        return {
            "message": "Display name updated successfully",
            "display_name": request.display_name.strip()
        }

    finally:
        conn.close()


@router.post("/change-status")
def change_status(
    request: dict,
    current_user=Depends(get_current_user)
):
    status = request.get("status", "").strip()[:100]

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET status = %s WHERE id = %s",
                (status, current_user["id"])
            )
        conn.commit()
        return {"message": "Status updated", "status": status}
    finally:
        conn.close()


@router.post("/upload-profile-photo")
def upload_profile_photo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP images are allowed")

    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{current_user['id']}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(file.file.read())

    photo_url = f"/uploads/avatars/{filename}"

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET profile_photo = %s WHERE id = %s",
                (photo_url, current_user["id"])
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "message": "Profile photo uploaded successfully",
        "profile_photo": photo_url
    }


@router.post("/register-fcm-token")
def register_fcm_token(
    request: dict,
    current_user=Depends(get_current_user)
):
    fcm_token = request.get("fcm_token", "").strip()
    if not fcm_token:
        raise HTTPException(status_code=400, detail="fcm_token is required")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET fcm_token = %s WHERE id = %s",
                (fcm_token, current_user["id"])
            )
        conn.commit()
        return {"message": "FCM token registered"}
    finally:
        conn.close()


@router.post("/feedback")
def submit_feedback(
    request: dict,
    current_user=Depends(get_current_user)
):
    feedback_type = request.get("type", "").strip()
    message = request.get("message", "").strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    if feedback_type not in ("bug", "feature", "other"):
        feedback_type = "other"

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO feedback (id, user_id, type, message)
                VALUES (%s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), current_user["id"], feedback_type, message)
            )
        conn.commit()
        return {"message": "Feedback submitted successfully"}
    finally:
        conn.close()