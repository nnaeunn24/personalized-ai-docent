from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(max_length=200)]
Category = Literal["VISUAL", "MEANING", "TECHNIQUE", "BACKGROUND"]
UnitStatus = Literal["pending", "reviewed", "published"]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtworkOrder(RequestBody):
    expected_ids: list[UUID]
    artwork_ids: list[UUID]


class Login(RequestBody):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class Refresh(RequestBody):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


RecoveryCode = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class RecoveryTokenHash(RequestBody):
    token_hash: RecoveryCode


class RecoveryCodeExchange(RequestBody):
    code: RecoveryCode
    verifier: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._~-]{43,128}$")]


class PasswordRecovery(RequestBody):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
    code_challenge: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")] | None = None


class PasswordReset(RequestBody):
    password: Annotated[str, StringConstraints(min_length=8, max_length=72)]


class Exhibition(RequestBody):
    name: Name
    description: Annotated[str, StringConstraints(max_length=20000)] = ""


class Visibility(RequestBody):
    is_public: bool


class Artwork(RequestBody):
    exhibition_id: UUID
    name: Name
    artist: ShortText = ""
    external_id: ShortText = ""
    description: Annotated[str, StringConstraints(max_length=100000)] = ""
    source_url: Annotated[str, StringConstraints(max_length=2048, pattern=r"^(https?://\S+)?$")] = ""
    language: Literal["", "ko", "en", "other"] = ""
    year: Annotated[str, StringConstraints(max_length=100)] = ""


class Unit(RequestBody):
    # Admin edits only supply content and category; provenance is managed by the database.
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    category: Category


class Review(RequestBody):
    updated_at: AwareDatetime
