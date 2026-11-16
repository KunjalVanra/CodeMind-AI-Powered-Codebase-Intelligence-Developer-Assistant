from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class RegistrationRequest(UserCredentials):
    full_name: str = Field(min_length=1, max_length=100)


class LoginRequest(UserCredentials):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class OAuth2TokenResponse(BaseModel):
    access_token: str
    token_type: str
