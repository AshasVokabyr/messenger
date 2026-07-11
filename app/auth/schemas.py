from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    login: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=255)


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
