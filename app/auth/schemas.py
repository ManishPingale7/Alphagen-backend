from pydantic import BaseModel
from typing import Optional

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    token_type: str
    id_token: Optional[str] = None

class UserInfo(BaseModel):
    sub: str
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None 