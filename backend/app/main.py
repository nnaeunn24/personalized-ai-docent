import json
import asyncio
import logging
from hashlib import sha256
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID
from weakref import WeakValueDictionary

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, AwareDatetime, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .docent import DEFAULT_DOCENT_REVIEW_ARTWORK_IDS
from .catalog_images import public_catalog_image
from .visitor import visitor_router
from .ai_settings import PromptKind, PromptTest, PromptUpdate
from .gemini_units import Gemini, classify_units, extract_units
from .followups import (
    FollowupEdit, FollowupPromptTest, GenerateFollowups, ReviewFollowups,
    complete, evidence_available, generate_followups, generation_units,
)
from .schemas import (
    Artwork, ArtworkOrder, Exhibition, Login, PasswordRecovery, PasswordReset, RecoveryCodeExchange,
    RecoveryTokenHash, Refresh, Review, Unit, UnitStatus, Visibility,
)


logger = logging.getLogger("uvicorn.error")
SETTINGS_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class AiSettingsMigrationRequired(HTTPException):
    def __init__(self):
        super().__init__(503, "Supabase에 05_admin_ai_settings.sql 마이그레이션을 적용해 주세요.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SETTINGS_ENV_FILE, extra="ignore")

    app_env: Literal["development", "test", "production"] = "production"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite",
        validation_alias=AliasChoices("GEMINI_MODEL", "GEMINI_EXTRACTION_MODEL"),
    )
    gemini_classification_model: str = ""
    gemini_docent_model: str = ""
    visitor_docent_unit_limit: int = Field(default=6, ge=1, le=6)
    visitor_docent_review_artwork_ids: list[UUID] = [
        UUID(artwork_id) for artwork_id in DEFAULT_DOCENT_REVIEW_ARTWORK_IDS
    ]
    visitor_docent_debug: bool = False
    visitor_docent_strategy_enabled: bool = True
    visitor_image_bucket: str = ""
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_secret_key: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache(maxsize=1)
def _cached_settings(env_file_mtime_ns: int | None):
    return Settings()


def settings():
    try:
        env_file_mtime_ns = SETTINGS_ENV_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        env_file_mtime_ns = None
    return _cached_settings(env_file_mtime_ns)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = settings()
    logger.info("Gemini configuration: key_present=%s extraction_model=%s classification_model=%s",
                bool(config.gemini_api_key.get_secret_value()), config.gemini_model,
                config.gemini_classification_model or config.gemini_model)
    async with httpx.AsyncClient(timeout=10.0) as client:
        app.state.http = client
        yield


app = FastAPI(title="Docent API", lifespan=lifespan)
app.include_router(visitor_router(settings))
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
bearer = HTTPBearer(auto_error=False)


async def supabase(request, method, path, *, token=None, params=None, payload=None, prefer=None):
    config = settings()
    key = config.supabase_publishable_key.get_secret_value() or config.supabase_secret_key.get_secret_value()
    if not config.supabase_url or not key:
        raise HTTPException(503, "Supabase settings are missing.")
    # Data API calls must always carry the verified user's JWT, even with a server API key.
    if path.startswith("/rest/v1/") and (not token or token.count(".") != 2):
        raise HTTPException(401, "A user access token is required.")
    headers = {"apikey": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prefer:
        headers["Prefer"] = prefer
    try:
        response = await request.app.state.http.request(
            method, config.supabase_url.rstrip("/") + path,
            headers=headers, params=params, json=payload,
        )
    except httpx.RequestError:
        raise HTTPException(503, "Supabase is unavailable.") from None
    if response.is_success:
        return response.json() if response.content else None
    if response.status_code == 429:
        raise HTTPException(429, "Too many requests. Try again later.")
    if path == "/auth/v1/user" and method == "PUT" and response.status_code in (400, 422):
        raise HTTPException(422, "Supabase rejected the new password.")
    if path == "/auth/v1/recover":
        raise HTTPException(502, "Supabase could not request the password recovery email.")
    if path.startswith("/auth/v1/") and response.status_code in (400, 401, 403, 422):
        raise HTTPException(401, "Invalid credentials or expired session.")
    if response.status_code in (401, 403):
        raise HTTPException(response.status_code, "Supabase denied this request.")
    if path == "/rest/v1/rpc/set_exhibition_artwork_order" and response.status_code == 404:
        raise HTTPException(503, "Supabase에 08_exhibition_artwork_order.sql을 적용해 주세요.")
    if path.startswith("/rest/v1/") and "followup" in path:
        if response.status_code == 404:
            raise HTTPException(503, "Supabase에 10_followup_questions.sql을 적용해 주세요.")
        if response.status_code == 409:
            raise HTTPException(409, "질문 또는 근거 Unit이 변경됐습니다. 새로고침 후 다시 시도해 주세요.")
        if response.status_code == 422:
            raise HTTPException(422, "두 HOW 답변과 유효한 Unit이 필요합니다. 게시하려면 근거 Unit도 게시해야 합니다.")
    if path in ("/rest/v1/admin_ai_active_prompts", "/rest/v1/admin_ai_prompt_versions",
                "/rest/v1/admin_ai_runs", "/rest/v1/rpc/set_admin_ai_prompt",
                "/rest/v1/rpc/store_prompted_artwork_extraction", "/rest/v1/rpc/store_verified_artwork_unit_extraction",
                "/rest/v1/artwork_unit_extractions"):
        try:
            error_code = response.json().get("code")
        except (ValueError, AttributeError):
            error_code = None
        if response.status_code == 404 or error_code in ("42703", "PGRST204", "PGRST205"):
            if path in ("/rest/v1/artwork_unit_extractions", "/rest/v1/rpc/store_verified_artwork_unit_extraction"):
                raise HTTPException(503, "Supabase에 03 및 04 Unit 추출 마이그레이션을 적용해 주세요.")
            raise AiSettingsMigrationRequired()
        if path == "/rest/v1/rpc/set_admin_ai_prompt" and response.status_code == 409:
            raise HTTPException(409, "다른 관리자가 활성 프롬프트를 변경했습니다. 최신 버전을 불러온 뒤 다시 시도해 주세요.")
        if response.status_code == 409:
            raise HTTPException(409, "작품의 Description이 변경되었거나 작품이 삭제되었습니다. 최신 내용을 불러와 다시 시도해 주세요.")
        if response.status_code == 422:
            raise HTTPException(422, "검수할 Unit을 저장하지 못했습니다. 추출을 다시 시도해 주세요.")
    if response.status_code == 409:
        raise HTTPException(409, "The record conflicts with existing data or its parent is missing.")
    if response.status_code == 400:
        raise HTTPException(422, "The database rejected the supplied data.")
    raise HTTPException(502, "Supabase could not complete the request.")


async def verify_admin(request: Request, token: str):
    user = await supabase(request, "GET", "/auth/v1/user", token=token)
    if user.get("is_anonymous") or user.get("role") != "authenticated" or not user.get("id"):
        raise HTTPException(403, "Administrator access is required.")
    rows = await supabase(
        request, "GET", "/rest/v1/admin_users", token=token,
        params={"select": "display_name", "user_id": f"eq.{user['id']}", "limit": 1},
    )
    if not rows:
        raise HTTPException(403, "Administrator access is required.")
    return {"id": user["id"], "email": user.get("email"), "display_name": rows[0]["display_name"]}


class Admin:
    def __init__(self, request, token, profile):
        self.request = request
        self.token = token
        self.profile = profile

    async def rows(self, table, method="GET", *, filters=None, payload=None):
        return await supabase(
            self.request, method, "/rest/v1/" + table, token=self.token,
            params=filters, payload=payload,
            prefer="return=representation" if method != "GET" else None,
        )


async def require_admin(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        raise HTTPException(401, "Bearer token required.", headers={"WWW-Authenticate": "Bearer"})
    return Admin(request, credentials.credentials, await verify_admin(request, credentials.credentials))


AdminAccess = Annotated[Admin, Depends(require_admin)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, error: RequestValidationError):
    # Validation errors can include the submitted password or refresh token.
    details = [{"loc": item["loc"], "msg": item["msg"]} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": details})


@app.get("/health")
async def health():
    return {"status": "ok"}


async def issue_session(request, response, grant, payload):
    session = await supabase(request, "POST", "/auth/v1/token", params={"grant_type": grant}, payload=payload)
    profile = await verify_admin(request, session["access_token"])
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "expires_in": session["expires_in"],
        "user": profile,
    }


@app.post("/api/admin/auth/login")
async def login(body: Login, request: Request, response: Response):
    return await issue_session(request, response, "password", body.model_dump())


@app.post("/api/admin/auth/refresh")
async def refresh(body: Refresh, request: Request, response: Response):
    return await issue_session(request, response, "refresh_token", body.model_dump())


@app.post("/api/admin/auth/logout", status_code=204)
async def logout(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if credentials is None:
        raise HTTPException(401, "Bearer token required.")
    await supabase(request, "POST", "/auth/v1/logout", token=credentials.credentials, params={"scope": "local"})


@app.post("/api/admin/auth/recover", status_code=204)
async def recover_password(body: PasswordRecovery, request: Request):
    origin = request.headers.get("origin", "")
    if not origin.startswith(("http://", "https://")) or origin not in settings().cors_origins:
        raise HTTPException(403, "This origin is not allowed for password recovery.")
    payload = {"email": body.email}
    if body.code_challenge:
        payload.update(code_challenge=body.code_challenge, code_challenge_method="s256")
    await supabase(
        request, "POST", "/auth/v1/recover",
        params={"redirect_to": origin + "/admin/reset-password"}, payload=payload,
    )


async def recovery_access_token(request, response, path, *, payload, params=None):
    session = await supabase(request, "POST", path, params=params, payload=payload)
    token = session.get("access_token") if isinstance(session, dict) else None
    if not token:
        raise HTTPException(401, "The recovery link is invalid or expired.")
    await verify_admin(request, token)
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token}


@app.post("/api/admin/auth/recover/verify")
async def verify_recovery_hash(body: RecoveryTokenHash, request: Request, response: Response):
    return await recovery_access_token(request, response, "/auth/v1/verify", payload={
        "token_hash": body.token_hash, "type": "recovery",
    })


@app.post("/api/admin/auth/recover/exchange")
async def exchange_recovery_code(body: RecoveryCodeExchange, request: Request, response: Response):
    return await recovery_access_token(request, response, "/auth/v1/token", params={"grant_type": "pkce"}, payload={
        "auth_code": body.code, "code_verifier": body.verifier,
    })


@app.put("/api/admin/auth/password", status_code=204)
async def reset_password(body: PasswordReset, admin: AdminAccess):
    await supabase(
        admin.request, "PUT", "/auth/v1/user", token=admin.token, payload=body.model_dump(),
    )


@app.get("/api/admin/me")
async def me(admin: AdminAccess):
    return admin.profile


def only_row(rows):
    if not rows:
        raise HTTPException(404, "Record not found.")
    return rows[0]


def by_id(record_id):
    return {"id": f"eq.{record_id}"}


def page(limit, offset, order="created_at.desc,id.asc"):
    return {"order": order, "limit": limit, "offset": offset}


def catalog_image_row(row, field):
    return {**row, "image_url": public_catalog_image(settings(), row.get(field))}


@app.post("/api/admin/catalog-images", status_code=201)
async def upload_catalog_image(request: Request, admin: AdminAccess):
    config = settings()
    key = config.supabase_publishable_key.get_secret_value() or config.supabase_secret_key.get_secret_value()
    if not config.visitor_image_bucket or not config.supabase_url or not key:
        raise HTTPException(503, "전시·작품 이미지 저장소가 설정되어 있지 않습니다.")
    signatures = {"image/jpeg": ("jpg", b"\xff\xd8\xff"), "image/png": ("png", b"\x89PNG\r\n\x1a\n")}
    media_type = request.headers.get("content-type")
    if media_type not in signatures:
        raise HTTPException(415, "JPG 또는 PNG 이미지를 선택해 주세요.")
    image = bytearray()
    async for chunk in request.stream():
        if len(image) + len(chunk) > 8 * 1024 * 1024:
            raise HTTPException(413, "8MB 이하의 이미지를 선택해 주세요.")
        image.extend(chunk)
    extension, signature = signatures[media_type]
    if not image.startswith(signature):
        raise HTTPException(422, "이미지 파일 형식이 올바르지 않습니다.")

    object_key = f"docent-catalog/{UUID(admin.profile['id'])}/{sha256(image).hexdigest()}.{extension}"
    bucket = quote(config.visitor_image_bucket, safe="")
    url = f"{config.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    public_url = public_catalog_image(config, object_key)
    client = request.app.state.http
    try:
        response = await client.post(
            url, content=bytes(image), timeout=30.0,
            headers={"apikey": key, "Authorization": f"Bearer {admin.token}", "Content-Type": media_type},
        )
        if not response.is_success:
            existing = await client.head(public_url)
            if not existing.is_success:
                logger.warning("Catalog image upload rejected: status=%s", response.status_code)
                raise HTTPException(502, "이미지를 저장하지 못했습니다. 이미지 버킷과 업로드 권한을 확인해 주세요.")
    except httpx.RequestError:
        raise HTTPException(503, "이미지 저장소에 연결하지 못했습니다.") from None
    return {"key": object_key}


@app.get("/api/admin/exhibitions")
async def exhibitions(admin: AdminAccess, limit: Limit = 50, offset: Offset = 0):
    return [catalog_image_row(row, "cover_object_key") for row in await admin.rows("exhibitions", filters=page(limit, offset))]


@app.post("/api/admin/exhibitions", status_code=201)
async def create_exhibition(body: Exhibition, admin: AdminAccess):
    row = only_row(await admin.rows("exhibitions", "POST", payload=body.model_dump(exclude_none=True)))
    return catalog_image_row(row, "cover_object_key")


@app.put("/api/admin/exhibitions/{record_id}")
async def update_exhibition(record_id: UUID, body: Exhibition, admin: AdminAccess):
    row = only_row(await admin.rows("exhibitions", "PATCH", filters=by_id(record_id),
                                   payload=body.model_dump(exclude_none=True)))
    return catalog_image_row(row, "cover_object_key")


@app.patch("/api/admin/exhibitions/{record_id}/visibility")
async def set_visibility(record_id: UUID, body: Visibility, admin: AdminAccess):
    row = only_row(await admin.rows("exhibitions", "PATCH", filters=by_id(record_id), payload=body.model_dump()))
    return catalog_image_row(row, "cover_object_key")


@app.delete("/api/admin/exhibitions/{record_id}", status_code=204)
async def delete_exhibition(record_id: UUID, admin: AdminAccess):
    only_row(await admin.rows("exhibitions", "DELETE", filters=by_id(record_id)))


@app.put("/api/admin/exhibitions/{exhibition_id}/artwork-order", status_code=204)
async def reorder_artworks(exhibition_id: UUID, body: ArtworkOrder, admin: AdminAccess):
    saved = await supabase(
        admin.request, "POST", "/rest/v1/rpc/set_exhibition_artwork_order", token=admin.token,
        payload={"exhibition_id": str(exhibition_id), **body.model_dump(mode="json")},
    )
    if not saved:
        raise HTTPException(409, "작품 목록 또는 순서가 변경되었습니다. 전시 상세를 새로고침해 주세요.")


@app.get("/api/admin/artworks")
async def artworks(admin: AdminAccess, exhibition_id: UUID | None = None, limit: Limit = 50, offset: Offset = 0):
    filters = page(limit, offset)
    if exhibition_id is not None:
        filters["exhibition_id"] = f"eq.{exhibition_id}"
    return [catalog_image_row(row, "image_object_key") for row in await admin.rows("artworks", filters=filters)]


@app.post("/api/admin/artworks", status_code=201)
async def create_artwork(body: Artwork, admin: AdminAccess):
    row = only_row(await admin.rows("artworks", "POST", payload=body.model_dump(mode="json", exclude_none=True)))
    return catalog_image_row(row, "image_object_key")


@app.put("/api/admin/artworks/{record_id}")
async def update_artwork(record_id: UUID, body: Artwork, admin: AdminAccess):
    row = only_row(await admin.rows("artworks", "PATCH", filters=by_id(record_id),
                                   payload=body.model_dump(mode="json", exclude_unset=True)))
    return catalog_image_row(row, "image_object_key")


@app.delete("/api/admin/artworks/{record_id}", status_code=204)
async def delete_artwork(record_id: UUID, admin: AdminAccess):
    only_row(await admin.rows("artworks", "DELETE", filters=by_id(record_id)))


async def active_ai_prompts(admin):
    rows = await admin.rows("admin_ai_active_prompts", filters={
        "select": "kind,version,prompt:admin_ai_prompt_versions!admin_ai_active_version_fkey(body)",
    })
    return {row["kind"]: {"version": row["version"], "body": row["prompt"]["body"].strip()} for row in rows}


@app.get("/api/admin/ai/prompts")
async def ai_prompts(admin: AdminAccess):
    return {"active": await active_ai_prompts(admin)}


@app.get("/api/admin/ai/prompts/{kind}/versions")
async def ai_prompt_versions(kind: PromptKind, admin: AdminAccess, limit: Limit = 20, offset: Offset = 0):
    return await admin.rows("admin_ai_prompt_versions", filters={
        **page(limit, offset, "version.desc"), "kind": f"eq.{kind}",
    })


@app.put("/api/admin/ai/prompts/{kind}")
async def change_ai_prompt(kind: PromptKind, body: PromptUpdate, admin: AdminAccess):
    if body.restore_version is not None:
        only_row(await admin.rows("admin_ai_prompt_versions", filters={
            "kind": f"eq.{kind}", "version": f"eq.{body.restore_version}", "select": "version",
        }))
    version = await supabase(admin.request, "POST", "/rest/v1/rpc/set_admin_ai_prompt", token=admin.token, payload={
        "prompt_kind": kind, "expected_version": body.expected_version,
        "new_body": body.body, "restore_version": body.restore_version,
    })
    return {"kind": kind, "version": version}


async def run_ai_pipeline(admin, description, prompts):
    config = settings()
    gemini = Gemini(admin.request.app.state.http, config.gemini_api_key.get_secret_value())
    extraction, classification = prompts["extraction"], prompts["classification"]
    extracted, extraction_model = await extract_units(gemini, config.gemini_model, description, extraction["body"])
    classified, classification_model = await classify_units(
        gemini, config.gemini_classification_model or config.gemini_model, extracted, classification["body"],
    )
    extraction_result = [unit.model_dump() for unit in extracted]
    classification_result = [unit.model_dump() for unit in classified]
    merged = [
        {**unit, **classification_result[index]} for index, unit in enumerate(extraction_result)
    ]
    return {
        "description": description,
        "extraction_prompt_version": extraction["version"], "classification_prompt_version": classification["version"],
        "extraction_prompt": extraction["body"], "classification_prompt": classification["body"],
        "extraction_model": extraction_model, "classification_model": classification_model,
        "extraction_result": extraction_result, "classification_result": classification_result,
    }, merged


@app.get("/api/admin/ai/tests")
async def ai_tests(admin: AdminAccess, limit: Limit = 10, offset: Offset = 0):
    return await admin.rows("admin_ai_runs", filters={**page(limit, offset), "mode": "eq.test"})


async def test_prompt(admin, kind, version, body):
    if version is not None:
        rows = await admin.rows("admin_ai_prompt_versions", filters={
            "kind": f"eq.{kind}", "version": f"eq.{version}", "select": "body",
        })
        if not rows or rows[0]["body"].strip() != body:
            version = None
    return {"version": version, "body": body}


@app.post("/api/admin/ai/tests", status_code=201)
async def create_ai_test(body: PromptTest, admin: AdminAccess):
    prompts = {
        "extraction": await test_prompt(admin, "extraction", body.extraction_version, body.extraction_body),
        "classification": await test_prompt(admin, "classification", body.classification_version, body.classification_body),
    }
    run, _ = await run_ai_pipeline(admin, body.description, prompts)
    return only_row(await admin.rows("admin_ai_runs", "POST", payload={**run, "mode": "test"}))

async def verified_units(admin, artwork_id, unit_ids):
    if not unit_ids:
        return []
    return await admin.rows("content_units", filters={
        "artwork_id": f"eq.{artwork_id}", "id": f"in.({','.join(unit_ids)})", "order": "number.asc",
    })


@app.post("/api/admin/artworks/{artwork_id}/units/extract")
async def extract_artwork_units(artwork_id: UUID, admin: AdminAccess):
    stage = "read_description"
    try:
        artwork = only_row(await admin.rows("artworks", filters={**by_id(artwork_id), "select": "description"}))
        description = artwork["description"]
        if not description.strip():
            raise HTTPException(422, "Unit을 추출하려면 Description을 입력해 주세요.")
        legacy_storage = False
        try:
            prompts = await active_ai_prompts(admin)
        except AiSettingsMigrationRequired:
            # Keep the installed extraction workflow usable until 05 is applied.
            legacy_storage = True
            prompts = {
                "extraction": {"version": None, "body": "Split the artwork description into distinct, standalone units in source order."},
                "classification": {"version": None, "body": "Choose by core information: VISUAL for appearance, MEANING for interpretation, TECHNIQUE for process, BACKGROUND for context. Flag mixed or ambiguous units."},
            }
        config = settings()
        if set(prompts) != {"extraction", "classification"}:
            raise HTTPException(503, "활성 추출 및 분류 프롬프트가 필요합니다.")
        revision = json.dumps([
            description, prompts["extraction"]["version"], prompts["classification"]["version"],
            config.gemini_model, config.gemini_classification_model or config.gemini_model,
        ], ensure_ascii=False)
        source_hash = sha256((description if legacy_storage else revision).encode()).hexdigest()
        stage = "read_previous_result"
        previous = await admin.rows("artwork_unit_extractions", filters={
            "artwork_id": f"eq.{artwork_id}", "source_hash": f"eq.{source_hash}", "select": "result_unit_ids",
        })
        if previous:
            units = await verified_units(admin, artwork_id, previous[0]["result_unit_ids"])
            if units:
                logger.info("Artwork extraction reused: artwork_id=%s verified=%d", artwork_id, len(units))
                return {"inserted_count": 0, "units": units}

        stage = "gemini_pipeline"
        logger.info("Artwork extraction started: artwork_id=%s model=%s", artwork_id, config.gemini_model)
        run, classified = await run_ai_pipeline(admin, description, prompts)
        logger.info("Artwork extraction classified: artwork_id=%s count=%d model=%s",
                    artwork_id, len(classified), run["classification_model"])
        stage = "supabase_store"
        payload = {
            "target_artwork": str(artwork_id), "expected_description": description,
            "extracted_units": classified,
        }
        if legacy_storage:
            endpoint = "store_verified_artwork_unit_extraction"
            payload.update(extractor=run["extraction_model"], classifier=run["classification_model"])
        else:
            endpoint = "store_prompted_artwork_extraction"
            payload.update(revision_hash=source_hash, run_data=run)
        result = await supabase(
            admin.request, "POST", "/rest/v1/rpc/" + endpoint, token=admin.token, payload=payload,
        )
        stage = "supabase_verify"
        units = await verified_units(admin, artwork_id, result.get("unit_ids") if isinstance(result, dict) else None)
        if not units:
            raise HTTPException(502, "Supabase에서 저장된 Unit을 확인하지 못했습니다. 추출을 다시 시도해 주세요.")
        inserted_count = result["inserted_count"]
        logger.info("Artwork extraction saved: artwork_id=%s inserted=%d verified=%d",
                    artwork_id, inserted_count, len(units))
        return {"inserted_count": inserted_count, "units": units}
    except HTTPException as error:
        logger.warning("Artwork extraction failed: artwork_id=%s stage=%s status=%d",
                       artwork_id, stage, error.status_code)
        raise

@app.get("/api/admin/units")
async def all_units(admin: AdminAccess, status: UnitStatus | None = None, limit: Limit = 50, offset: Offset = 0):
    return await list_units(admin, status, limit, offset)


async def list_units(admin, status, limit, offset, artwork_id=None):
    filters = page(limit, offset, "number.asc")
    if artwork_id is not None:
        filters["artwork_id"] = f"eq.{artwork_id}"
    if status is not None:
        filters["status"] = f"eq.{status}"
    return await admin.rows("content_units", filters=filters)


@app.get("/api/admin/artworks/{artwork_id}/units")
async def units(artwork_id: UUID, admin: AdminAccess, status: UnitStatus | None = None, limit: Limit = 50, offset: Offset = 0):
    return await list_units(admin, status, limit, offset, artwork_id)


@app.post("/api/admin/artworks/{artwork_id}/units", status_code=201)
async def create_unit(artwork_id: UUID, body: Unit, admin: AdminAccess):
    return only_row(await admin.rows(
        "content_units", "POST", payload={**body.model_dump(), "artwork_id": str(artwork_id)},
    ))


@app.put("/api/admin/units/{record_id}")
async def update_unit(record_id: UUID, body: Unit, admin: AdminAccess):
    return only_row(await admin.rows("content_units", "PATCH", filters=by_id(record_id), payload=body.model_dump()))


@app.post("/api/admin/units/{record_id}/review")
async def review_unit(record_id: UUID, body: Review, admin: AdminAccess, background_tasks: BackgroundTasks):
    filters = {**by_id(record_id), "status": "eq.pending", "updated_at": f"eq.{body.updated_at.isoformat()}"}
    rows = await admin.rows("content_units", "PATCH", filters=filters, payload={"status": "reviewed"})
    if not rows:
        raise HTTPException(409, "The unit changed or is no longer pending. Reload it before reviewing.")
    background_tasks.add_task(auto_generate_followups, admin, UUID(rows[0]["artwork_id"]))
    return rows[0]


@app.post("/api/admin/artworks/{artwork_id}/units/publish")
async def publish_units(artwork_id: UUID, admin: AdminAccess):
    filters = {"artwork_id": f"eq.{artwork_id}", "status": "eq.reviewed"}
    rows = await admin.rows("content_units", "PATCH", filters=filters, payload={"status": "published"})
    if not rows:
        raise HTTPException(409, "No reviewed units to publish.")
    return {"units": rows}


@app.delete("/api/admin/units/{record_id}", status_code=204)
async def delete_unit(record_id: UUID, admin: AdminAccess):
    only_row(await admin.rows("content_units", "DELETE", filters=by_id(record_id)))


followup_generation_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()


async def followup_units(admin, artwork_id):
    return await admin.rows("content_units", filters={
        "artwork_id": f"eq.{artwork_id}", "select": "id,number,category,content,status", "order": "number.asc",
    })


async def followup_rows(admin, artwork_id):
    return await admin.rows("followup_questions", filters={
        "artwork_id": f"eq.{artwork_id}", "order": "priority.asc,id.asc",
    })


async def followup_rpc(admin, operation, payload):
    return await supabase(admin.request, "POST", "/rest/v1/rpc/" + operation, token=admin.token, payload=payload)


async def followup_model(admin, prompt, artwork, units, existing, limits, targets):
    config = settings()
    gemini = Gemini(admin.request.app.state.http, config.gemini_api_key.get_secret_value())
    return await generate_followups(gemini, config.gemini_docent_model or config.gemini_model,
                                    prompt, artwork, units, existing, limits, targets)


async def prepare_followups(admin, artwork_id, options, automatic=False):
    lock = followup_generation_locks.setdefault(artwork_id, asyncio.Lock())
    if lock.locked() and not automatic:
        raise HTTPException(409, "이 작품의 후속 질문을 이미 생성하고 있습니다.")
    async with lock:
        artwork = only_row(await admin.rows("artworks", filters=by_id(artwork_id)))
        all_units = await followup_units(admin, artwork_id)
        units = generation_units(all_units)
        if automatic and (not units or len(units) != len(all_units)):
            return {"generated": 0}
        if not units:
            raise HTTPException(422, "검수 완료 또는 게시된 Unit이 필요합니다.")
        existing = await followup_rows(admin, artwork_id)
        unit_ids = {unit["id"] for unit in units}
        requested = [row for row in existing if not options.category or row["category"] == options.category]
        if options.question_id:
            target = only_row([row for row in existing if row["id"] == str(options.question_id)])
            if complete(target) and not options.replace:
                raise HTTPException(409, "기존 답변을 교체하려면 재생성을 확인해 주세요.")
            if not evidence_available(target, unit_ids):
                raise HTTPException(422, "연결된 Unit을 다시 검수하거나 질문의 근거를 수정해 주세요.")
            targets = [{**target, "replace_answers": options.replace}]
            limits = {}
            kept = existing
        else:
            if options.replace and not options.category:
                raise HTTPException(422, "재생성할 카테고리를 선택해 주세요.")
            kept = [row for row in existing if row not in requested] if options.replace else existing
            targets = [] if options.replace else [row for row in requested if not complete(row) and evidence_available(row, unit_ids)]
            limits = {category: max(0, 2 - sum(row["category"] == category for row in kept))
                      for category in {unit["category"] for unit in units}
                      if not options.category or category == options.category}
        if not any(limits.values()) and not targets:
            return {"generated": 0}
        prompt = (await active_ai_prompts(admin)).get("followup")
        if not prompt:
            raise HTTPException(503, "Supabase에 10_followup_questions.sql을 적용해 주세요.")
        generated, _ = await followup_model(admin, prompt["body"], artwork, units, kept, limits, targets)
        if generated:
            await followup_rpc(admin, "store_followup_generation", {
                "target_artwork": str(artwork_id),
                "expected_pool": {row["id"]: row["updated_at"] for row in existing},
                "expected_units": {unit["id"]: [unit["category"], unit["content"]] for unit in units},
                "replacements": [row["id"] for row in requested] if options.replace and not options.question_id else [],
                "generated": generated,
            })
        return {"generated": len(generated)}


async def auto_generate_followups(admin, artwork_id):
    try:
        await prepare_followups(admin, artwork_id, GenerateFollowups(), automatic=True)
    except HTTPException as error:
        logger.warning("Automatic follow-up generation failed: artwork=%s status=%s", artwork_id, error.status_code)


@app.get("/api/admin/followups")
async def followup_overview(admin: AdminAccess, limit: Limit = 50, offset: Offset = 0):
    return await admin.rows("followup_questions", filters={
        **page(limit, offset), "select": "id,artwork_id,review_status",
    })


@app.get("/api/admin/artworks/{artwork_id}/followups")
async def get_followups(artwork_id: UUID, admin: AdminAccess):
    return {"questions": await followup_rows(admin, artwork_id), "units": await followup_units(admin, artwork_id)}


@app.post("/api/admin/artworks/{artwork_id}/followups/generate")
async def generate_artwork_followups(artwork_id: UUID, body: GenerateFollowups, admin: AdminAccess):
    return await prepare_followups(admin, artwork_id, body)


@app.put("/api/admin/artworks/{artwork_id}/followups/{question_id}")
async def edit_followup(artwork_id: UUID, question_id: UUID, body: FollowupEdit, admin: AdminAccess):
    if len(set(body.related_unit_ids)) != len(body.related_unit_ids):
        raise HTTPException(422, "근거 Unit을 중복 선택할 수 없습니다.")
    units = await followup_units(admin, artwork_id)
    if not set(map(str, body.related_unit_ids)) <= {unit["id"] for unit in units}:
        raise HTTPException(422, "이 작품의 Unit만 연결할 수 있습니다.")
    rows = await admin.rows("followup_questions", "PATCH", filters={
        **by_id(question_id), "artwork_id": f"eq.{artwork_id}", "updated_at": f"eq.{body.updated_at.isoformat()}",
    }, payload=body.model_dump(mode="json", exclude={"updated_at"}))
    if not rows:
        raise HTTPException(409, "다른 관리자가 질문을 변경했습니다. 새로고침해 주세요.")
    return rows[0]


@app.post("/api/admin/artworks/{artwork_id}/followups/review", status_code=204)
async def update_followup_status(artwork_id: UUID, body: ReviewFollowups, admin: AdminAccess):
    await followup_rpc(admin, "review_followup_questions", {
        "target_artwork": str(artwork_id), "expected_rows": body.model_dump(mode="json")["items"],
        "next_status": body.status,
    })


@app.delete("/api/admin/artworks/{artwork_id}/followups/{question_id}", status_code=204)
async def delete_followup(artwork_id: UUID, question_id: UUID, admin: AdminAccess, updated_at: AwareDatetime):
    rows = await admin.rows("followup_questions", "DELETE", filters={
        **by_id(question_id), "artwork_id": f"eq.{artwork_id}", "updated_at": f"eq.{updated_at.isoformat()}",
    })
    if not rows:
        raise HTTPException(409, "질문이 변경됐습니다. 새로고침해 주세요.")


@app.post("/api/admin/ai/followup-tests")
async def test_followup_generation(body: FollowupPromptTest, admin: AdminAccess):
    artwork = only_row(await admin.rows("artworks", filters=by_id(body.artwork_id)))
    selected = set(map(str, body.unit_ids))
    units = [unit for unit in generation_units(await followup_units(admin, body.artwork_id)) if unit["id"] in selected]
    if len(units) != len(selected):
        raise HTTPException(422, "선택한 근거 중 검수 완료 상태가 아닌 Unit이 있습니다.")
    prompt = await test_prompt(admin, "followup", body.version, body.body)
    questions, model = await followup_model(admin, prompt["body"], artwork, units, [],
                                           {unit["category"]: 2 for unit in units}, [])
    return {"artwork": {"id": artwork["id"], "name": artwork["name"]},
            "units": units, "version": prompt["version"], "model": model, "questions": questions}
