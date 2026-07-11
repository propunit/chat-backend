from pydantic import BaseModel, Field
from typing import Literal, Optional


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    display_name: str = Field("", max_length=100)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatMessage(BaseModel):
    receiver_id: str
    type: Literal["text", "image", "video", "file", "audio", "location", "gif", "sticker"] = "text"
    content: str
    reply_to_id: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class ChangeDisplayNameRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)


class FcmTokenRequest(BaseModel):
    token: str
