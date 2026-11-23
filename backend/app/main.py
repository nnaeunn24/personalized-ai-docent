import json
import logging
from hashlib import sha256
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .docent import DEFAULT_DOCENT_REVIEW_ARTWORK_IDS
from .visitor import visitor_router
from .ai_settings import PromptKind, PromptTest, PromptUpdate
from .gemini_units import Gemini, classify_units, extract_units
from .schemas import (
    Artwork, ArtworkOrder, Exhibition, Login, PasswordRecovery, PasswordReset, RecoveryCodeExchange,
    RecoveryTokenHash, Refresh, Review, Unit, UnitStatus, Visibility,
)


logger = logging.getLogger("uvicorn.error")


class AiSettingsMigrationRequired(HTTPException):
    def __init__(self):
        super().__init__(503, "Supabase에 05_admin_ai_settings.sql 마이그레이션을 적용해 주세요.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

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
    visitor_docent_strategy_enabled: bool = False
    visitor_image_bucket: str = ""
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_secret_key: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def settings():
    return Settings()


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


@app.get("/api/admin/exhibitions")
async def exhibitions(admin: AdminAccess, limit: Limit = 50, offset: Offset = 0):
    return await admin.rows("exhibitions", filters=page(limit, offset))


@app.post("/api/admin/exhibitions", status_code=201)
async def create_exhibition(body: Exhibition, admin: AdminAccess):
    return only_row(await admin.rows("exhibitions", "POST", payload=body.model_dump()))


@app.put("/api/admin/exhibitions/{record_id}")
async def update_exhibition(record_id: UUID, body: Exhibition, admin: AdminAccess):
    return only_row(await admin.rows("exhibitions", "PATCH", filters=by_id(record_id), payload=body.model_dump()))


@app.patch("/api/admin/exhibitions/{record_id}/visibility")
async def set_visibility(record_id: UUID, body: Visibility, admin: AdminAccess):
    return only_row(await admin.rows("exhibitions", "PATCH", filters=by_id(record_id), payload=body.model_dump()))


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
    return await admin.rows("artworks", filters=filters)


@app.post("/api/admin/artworks", status_code=201)
async def create_artwork(body: Artwork, admin: AdminAccess):
    return only_row(await admin.rows("artworks", "POST", payload=body.model_dump(mode="json")))


@app.put("/api/admin/artworks/{record_id}")
async def update_artwork(record_id: UUID, body: Artwork, admin: AdminAccess):
    return only_row(await admin.rows("artworks", "PATCH", filters=by_id(record_id), payload=body.model_dump(mode="json", exclude_unset=True)))


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
async def review_unit(record_id: UUID, body: Review, admin: AdminAccess):
    filters = {**by_id(record_id), "status": "eq.pending", "updated_at": f"eq.{body.updated_at.isoformat()}"}
    rows = await admin.rows("content_units", "PATCH", filters=filters, payload={"status": "reviewed"})
    if not rows:
        raise HTTPException(409, "The unit changed or is no longer pending. Reload it before reviewing.")
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
