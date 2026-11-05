from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, Field, StringConstraints, field_validator

Key = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class PushKeys(BaseModel):
    p256dh: Key
    auth: Key


def _https_endpoint(value: str) -> str:
    if not value.startswith("https://") or len(value) > 2048:
        raise ValueError("endpoint must be an https URL of at most 2048 characters")
    AnyHttpUrl(value)
    return value


class PushSubscribeIn(BaseModel):
    endpoint: str
    keys: PushKeys

    _check = field_validator("endpoint")(_https_endpoint)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2048)


class PublicKeyOut(BaseModel):
    key: str


class PushResult(BaseModel):
    sent: int
    removed: int


class RunRemindersOut(BaseModel):
    due: int
    sent: int
    removed: int
