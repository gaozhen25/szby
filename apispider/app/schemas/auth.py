from pydantic import BaseModel, EmailStr, Field


class UserSchema(BaseModel):
    id: str
    email: EmailStr
    nickname: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class AuthResponse(BaseModel):
    accessToken: str
    tokenType: str = "Bearer"
    user: UserSchema
