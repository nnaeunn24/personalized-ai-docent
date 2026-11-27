from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints

from .artwork_questions import ArtworkAnswer, ArtworkQuestion, answer_artwork_question
from .docent import (
    DOCENT_DELIVERY, DOCENT_EXPERIENCE, EVIDENCE_PROMPT, VISITOR_DOCENT_PROMPT,
    DocentText, EvidencePlan, Personalization, SupportingLink, apply_evidence_plan, select_units, sentence_count,
)
from .docent_strategy import (
    DOCENT_FLOW_RULES, DocentStrategyAssessment,
    assess_docent_strategy, plan_docent_strategy,
)
from .gemini_units import Gemini, logger
from .schemas import Category
from .followups import HowLevel, VisitorFollowup
from .voice import synthesize_speech
from .catalog_images import public_catalog_image


class ExhibitionSummary(BaseModel):
    id: UUID
    name: str
    code: str
    description: str | None = None
    image_url: str | None = None


class ArtworkSummary(BaseModel):
    id: UUID
    name: str
    artist: str
    year: str
    image_url: str | None = None


class ExhibitionDetail(BaseModel):
    id: UUID
    name: str
    description: str
    artworks: list[ArtworkSummary]
    image_url: str | None = None


class ArtworkExhibition(BaseModel):
    id: UUID
    name: str


class PublishedUnit(BaseModel):
    id: UUID
    content: str
    category: Category


class ArtworkDetail(ArtworkSummary):
    exhibition: ArtworkExhibition
    units: list[PublishedUnit]


class SelectedUnit(BaseModel):
    id: UUID
    category: Category


class ExcludedUnit(SelectedUnit):
    reason: str


class StrategyDebug(BaseModel):
    status: Literal["applied", "planning_fallback", "no_core"]
    required_content: list[dict] | None = None
    explanation_strategy: dict | None = None
    evidence_refs: dict[int, UUID] | None = None
    assessment: DocentStrategyAssessment | None = None


class DocentDebug(BaseModel):
    personalization: Personalization
    selected_units: list[SelectedUnit]
    model: str | None
    core_units: list[SelectedUnit]
    supporting_units: list[SelectedUnit]
    excluded_units: list[ExcludedUnit]
    used_core_unit_ids: list[UUID]
    used_supporting_unit_ids: list[UUID]
    sentence_count: int
    character_count: int
    evidence_insufficient: bool
    selection_strategy: str
    supporting_links: list[SupportingLink]
    selection_details: dict | None = None
    strategy_details: StrategyDebug | None = None


class DocentResult(BaseModel):
    text: str | None
    debug: DocentDebug | None = None


class SpeechRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
    why: Literal["discover", "relax", "reflect", "together"]


def visitor_router(settings):
    router = APIRouter(prefix="/api/visitor", tags=["Visitor"])

    async def read_catalog(
        request: Request, response: Response,
        operation: Literal["visitor_exhibitions", "visitor_exhibition", "visitor_artwork", "visitor_followup_questions"],
        params: dict[str, str],
    ):
        config = settings()
        key = config.supabase_publishable_key.get_secret_value()
        if not config.supabase_url or not key:
            raise HTTPException(503, "공개 조회용 Supabase 설정을 확인해 주세요.")
        try:
            result = await request.app.state.http.post(
                config.supabase_url.rstrip("/") + "/rest/v1/rpc/" + operation,
                headers={"apikey": key}, json=params,
            )
        except httpx.RequestError:
            raise HTTPException(503, "공개 데이터를 불러올 수 없습니다.") from None
        response.headers["Cache-Control"] = "no-store"
        if operation == "visitor_followup_questions" and result.status_code == 404:
            return []
        if not result.is_success:
            raise HTTPException(503, "공개 데이터를 불러올 수 없습니다.")
        if not result.content:
            return None
        try:
            return result.json()
        except ValueError:
            raise HTTPException(502, "공개 데이터 응답을 읽을 수 없습니다.") from None

    def public_record(record):
        if record is None:
            raise HTTPException(404, "공개된 전시 또는 작품을 찾을 수 없습니다.", headers={"Cache-Control": "no-store"})
        return record

    def with_image(record):
        record["image_url"] = public_catalog_image(settings(), record.get("image_object_key"))
        return record

    @router.get("/exhibitions", response_model=list[ExhibitionSummary])
    async def exhibitions(request: Request, response: Response):
        return [with_image(row) for row in await read_catalog(request, response, "visitor_exhibitions", {})]

    @router.get("/exhibitions/{exhibition_id}", response_model=ExhibitionDetail)
    async def exhibition(exhibition_id: UUID, request: Request, response: Response):
        record = public_record(await read_catalog(
            request, response, "visitor_exhibition", {"exhibition_id": str(exhibition_id)},
        ))
        return {**with_image(record), "artworks": [with_image(row) for row in record["artworks"]]}

    @router.get("/exhibitions/{exhibition_id}/artworks/{artwork_id}", response_model=ArtworkDetail)
    async def artwork(exhibition_id: UUID, artwork_id: UUID, request: Request, response: Response):
        return with_image(public_record(await read_catalog(request, response, "visitor_artwork", {
            "exhibition_id": str(exhibition_id), "artwork_id": str(artwork_id),
        })))

    @router.get(
        "/exhibitions/{exhibition_id}/artworks/{artwork_id}/suggested-questions",
        response_model=list[VisitorFollowup],
    )
    async def suggested_questions(exhibition_id: UUID, artwork_id: UUID,
                                  request: Request, response: Response, how: HowLevel = "Basic"):
        return await read_catalog(request, response, "visitor_followup_questions", {
            "exhibition_id": str(exhibition_id), "artwork_id": str(artwork_id), "how_level": how,
        })

    @router.post("/speech", response_class=Response)
    async def speech(body: SpeechRequest, request: Request):
        config = settings()
        audio = await synthesize_speech(request.app.state.http, body.text, body.why, config)
        return Response(content=audio, media_type="audio/wav")

    @router.post(
        "/exhibitions/{exhibition_id}/artworks/{artwork_id}/docent",
        response_model=DocentResult, response_model_exclude_unset=True,
    )
    async def docent(exhibition_id: UUID, artwork_id: UUID, profile: Personalization,
                     request: Request, response: Response):
        record = await artwork(exhibition_id, artwork_id, request, response)
        data = ArtworkDetail.model_validate(record)
        config = settings()
        debug_enabled = config.app_env == "development" and config.visitor_docent_debug
        artwork_metadata = data.model_dump(include={"name", "artist", "year"})
        selection = select_units(
            data.units, profile.what, config.visitor_docent_unit_limit, artwork_metadata,
            artwork_needs_review=artwork_id in config.visitor_docent_review_artwork_ids,
            why=profile.why, how=profile.how,
        )
        text = model = None
        used_core = []
        used_supporting = []
        evidence_insufficient = not selection.core
        strategy_debug = None
        if config.visitor_docent_strategy_enabled:
            strategy_debug = StrategyDebug(status="no_core")
        if selection.core or selection.supporting:
            gemini = Gemini(request.app.state.http, config.gemini_api_key.get_secret_value())
            model_name = config.gemini_docent_model or config.gemini_model
            candidates = sorted(
                (unit for unit in data.units if selection.excluded.get(unit.id) != "duplicate"),
                key=lambda unit: unit.id,
            )
            if selection.core and len(candidates) > 1:
                candidate_refs = dict(enumerate(candidates, start=1))
                plan_input = {
                    "artwork_name": data.name,
                    "WHAT": profile.what,
                    "WHY": profile.why,
                    "HOW": profile.how,
                    "unit_limit": config.visitor_docent_unit_limit,
                    "core_candidates": [],
                    "supporting_candidates": [],
                }
                for ref, unit in candidate_refs.items():
                    role = "core_candidates" if unit.category == profile.what else "supporting_candidates"
                    plan_input[role].append({"ref": ref, "category": unit.category, "content": unit.content})
                semantic_selection = None
                try:
                    plan, _ = await gemini.generate(model_name, EVIDENCE_PROMPT, plan_input, EvidencePlan)
                    semantic_selection = apply_evidence_plan(
                        candidate_refs, profile.what, config.visitor_docent_unit_limit, selection, plan,
                        artwork_metadata, why=profile.why, how=profile.how,
                    )
                except HTTPException as error:
                    logger.warning("Docent evidence planning unavailable: status=%s", error.status_code)
                    selection.trace["plan_status"] = "provider_or_schema_error"
                if semantic_selection is not None:
                    selection = semantic_selection
                else:
                    selection.strategy = "lexical_fallback"
            input_data = {
                "artwork": artwork_metadata,
                "core_units": [unit.model_dump(mode="json") for unit in selection.core],
                "supporting_units": [unit.model_dump(mode="json") for unit in selection.supporting],
                "WHY": profile.why,
                "WHAT": profile.what,
                "HOW": profile.how,
                "WHY_GUIDANCE": DOCENT_EXPERIENCE[profile.why],
                "HOW_GUIDANCE": DOCENT_DELIVERY[profile.how],
            }
            if selection.links:
                input_data["supporting_links"] = [link.model_dump(mode="json") for link in selection.links]
            try:
                instruction = VISITOR_DOCENT_PROMPT
                if config.visitor_docent_strategy_enabled and selection.core:
                    try:
                        strategy_fields = await plan_docent_strategy(
                            gemini, model_name, {**input_data, "CONTEXT": profile.context or None},
                        )
                    except (HTTPException, ValueError) as error:
                        logger.warning("Docent strategy planning failed: %s", type(error).__name__)
                        strategy_debug = StrategyDebug(status="planning_fallback")
                    else:
                        instruction = f"{instruction}\n\n{DOCENT_FLOW_RULES}"
                        input_data.update(strategy_fields)
                        strategy_debug = StrategyDebug(
                            status="applied", required_content=strategy_fields["required_content"],
                            explanation_strategy=strategy_fields["explanation_strategy"],
                            evidence_refs=strategy_fields["evidence_refs"], assessment=None,
                        )
                result, model = await gemini.generate(model_name, instruction, input_data, DocentText)
                used_core = result.used_core_unit_ids
                used_supporting = result.used_supporting_unit_ids
                if (bool(selection.core) != bool(used_core)
                    or not (used_core or used_supporting)
                    or len(set(used_core)) != len(used_core)
                    or len(set(used_supporting)) != len(used_supporting)
                    or not set(used_core).issubset(unit.id for unit in selection.core)
                    or not set(used_supporting).issubset(unit.id for unit in selection.supporting)):
                    logger.warning("Docent validation failed: category=evidence_id_mismatch schema=DocentText")
                    raise HTTPException(502, "도슨트 응답의 근거 ID가 제공된 Unit과 일치하지 않습니다.")
            except HTTPException as error:
                if error.status_code == 502:
                    raise HTTPException(502, "도슨트 설명을 생성하지 못했습니다.") from None
                raise
            text = result.text
            evidence_insufficient = evidence_insufficient or result.evidence_insufficient
            if debug_enabled and strategy_debug and strategy_debug.status == "applied":
                try:
                    strategy_debug.assessment = await assess_docent_strategy(gemini, model_name, input_data, text)
                except (HTTPException, ValueError) as error:
                    logger.warning("Docent strategy assessment unavailable: %s", type(error).__name__)
        if debug_enabled:
            debug = DocentDebug(
                personalization=profile,
                selected_units=[SelectedUnit(id=unit.id, category=unit.category)
                                for unit in selection.core + selection.supporting],
                model=model,
                core_units=[SelectedUnit(id=unit.id, category=unit.category) for unit in selection.core],
                supporting_units=[SelectedUnit(id=unit.id, category=unit.category) for unit in selection.supporting],
                excluded_units=[
                    ExcludedUnit(id=unit.id, category=unit.category, reason=selection.excluded[unit.id])
                    for unit in data.units if unit.id in selection.excluded
                ],
                used_core_unit_ids=used_core,
                used_supporting_unit_ids=used_supporting,
                sentence_count=sentence_count(text or ""),
                character_count=len(text or ""),
                evidence_insufficient=evidence_insufficient,
                selection_strategy=selection.strategy,
                supporting_links=selection.links,
                selection_details=selection.trace or None,
            )
            if strategy_debug is not None:
                debug.strategy_details = strategy_debug
            return DocentResult(text=text, debug=debug)
        return DocentResult(text=text)

    @router.post("/exhibitions/{exhibition_id}/artworks/{artwork_id}/questions", response_model=ArtworkAnswer)
    async def question(exhibition_id: UUID, artwork_id: UUID, conversation: ArtworkQuestion,
                       request: Request, response: Response):
        data = ArtworkDetail.model_validate(await artwork(exhibition_id, artwork_id, request, response))
        config = settings()
        gemini = Gemini(request.app.state.http, config.gemini_api_key.get_secret_value())
        return await answer_artwork_question(
            gemini, config.gemini_docent_model or config.gemini_model,
            data.model_dump(include={"name", "artist", "year"}), data.units, conversation,
        )

    return router
