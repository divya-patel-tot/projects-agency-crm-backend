from uuid import UUID

from pydantic import BaseModel, Field


class LoginInput(BaseModel):
    email: str
    password: str = Field(min_length=8)


class VerifyTotpInput(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=6)


class TotpConfirmInput(BaseModel):
    code: str = Field(min_length=6, max_length=6)
