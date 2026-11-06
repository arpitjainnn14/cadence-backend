from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    email: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)
