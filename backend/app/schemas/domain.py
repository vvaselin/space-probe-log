from datetime import datetime

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class AdminSessionRead(BaseModel):
    authenticated: bool
    username: str
    csrf_token: str
    expires_at: datetime
