from pydantic import BaseModel


class RegisterRequest(BaseModel):
    login: str
    password: str


class LoginRequest(BaseModel):
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
