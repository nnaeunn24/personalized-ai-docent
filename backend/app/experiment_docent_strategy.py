"""Run a fixed-evidence CONTEXT experiment outside the visitor generation route."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import Field, StringConstraints

from .docent import DOCENT_PROMPT, HOW_FOCUS, WHY_GUIDANCE, DocentText
from .docent_strategy import (
    AUTOMATIC_PROMPT, BOUNDARIES, STRATEGY_GENERATION_RULES, STRATEGY_PROMPT,
    AutomaticStrategy, ExplanationStrategy, validate_automatic_strategy, validate_strategy,
)
from .gemini_units import Gemini
from .main import app, settings
from .schemas import RequestBody


class ContextCase(RequestBody):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    context: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
    repeats: int = Field(default=1, ge=1)


CONDITIONS = {
    "none": "",
    "breakup": "최근 이별을 경험했어요.",
    "new_beginning": "새로운 시작을 앞두고 있어요.",
    "plant_care": "최근 집에서 식물을 돌보면서 편안함을 느꼈어요.",
}

VIEWING_UNIT_IDS = {
    "e88cfab4-5073-42e2-b737-c6a23700a7ab",  # The figures' contrasting postures.
    "45a0030e-167d-4902-a14a-0bfd1af265ac",  # The central geranium's stem and leaves.
}

# Curated viewing hypotheses for this artwork and evidence set. They are not
# production rules for inferring a visitor's emotions or interests from free text.
VIEWING_BRIEFS = {
    "none": (
        "정물 사이에 그려진 인물 형상을 먼저 알아보게 한다. 두 자세를 비교하고 "
        "사물의 배치에 사람 형상이 더해질 때 화면이 어떻게 읽히는지 설명한다.", None,
    ),
    "breakup": (
        "정물 사이에 그려진 인물 형상을 먼저 알아보게 한다. 두 자세를 비교하고 "
        "사물의 배치에 사람 형상이 더해질 때 화면이 어떻게 읽히는지 설명한다.", None,
    ),
    "new_beginning": (
        "움직임이 느껴지는 남성 인물의 자세에 먼저 주목한다. 고정된 사물들 사이의 "
        "인물 형상이 장면에 움직임을 연상시키는 지점과 정물의 관계를 설명한다.",
        "남성 인물에서 움직임이 느껴지는 자세를 먼저 찾고, 안정적으로 자리 잡은 여성 인물과 비교한다.",
    ),
    "plant_care": (
        "식물을 관찰하는 방식으로 시작한다. 제라늄의 수직 줄기와 넓게 퍼지는 잎을 따라가며 "
        "주변 사물이 어떻게 한 구성으로 묶여 보이는지 설명한다.",
        "제라늄의 줄기를 위로 따라가 본 뒤 잎이 옆으로 펼쳐지는 방향으로 시선을 옮겨 주변 사물과 연결해 본다.",
    ),
}


async def generate_automatic(gemini, model, instruction, source, schema):
    for attempt in range(4):
        try:
            return await gemini.generate(model, instruction, source, schema)
        except HTTPException as error:
            if error.status_code != 429 or attempt == 3:
                raise
            print("Gemini rate limited; retrying this step", flush=True)
            await asyncio.sleep(25)


async def run_experiment(snapshot, core_ids, supporting_ids, cases=None):
    profile = {"why": "discover", "what": "MEANING", "how": "Basic"}
    recorded = snapshot["artwork"]
    path = f"/api/visitor/exhibitions/{recorded['exhibition']['id']}/artworks/{recorded['id']}"
    config = settings()
    if UUID(recorded["id"]) in config.visitor_docent_review_artwork_ids:
        raise ValueError("Artwork is pending catalog review")
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as visitor:
        response = await visitor.get(path)
        response.raise_for_status()
        artwork = response.json()
        if artwork != recorded:
            raise ValueError("Published artwork differs from the recorded snapshot")
        available = {unit["id"]: unit for unit in artwork["units"]}
        all_ids = core_ids + supporting_ids
        if (not core_ids or len(supporting_ids) > 2 or len(all_ids) > config.visitor_docent_unit_limit
            or len(set(all_ids)) != len(all_ids)
            or not set(all_ids) <= available.keys()):
            raise ValueError("Fixed evidence exceeds the limits or contains repeated or unpublished IDs")
        if cases is None and set(supporting_ids) != VIEWING_UNIT_IDS:
            raise ValueError("This experiment requires the two visual Units used by its viewing hypotheses")
        core = [available[unit_id] for unit_id in core_ids]
        supporting = [available[unit_id] for unit_id in supporting_ids]
        if any(unit["category"] != profile["what"] for unit in core) or any(
            unit["category"] == profile["what"] for unit in supporting
        ):
            raise ValueError("Fixed evidence roles must agree with WHAT")
        evidence = dict(enumerate(core + supporting, 1))
        core_refs = set(range(1, len(core) + 1))
        metadata = {key: artwork[key] for key in ("name", "artist", "year")}
        gemini = Gemini(app.state.http, config.gemini_api_key.get_secret_value())
        model = config.gemini_docent_model or config.gemini_model
        base = {
            "artwork": metadata, "core_units": core, "supporting_units": supporting,
            "WHY": WHY_GUIDANCE[profile["why"]], "WHAT": profile["what"], "HOW": profile["how"],
            "evidence_refs": {ref: unit["id"] for ref, unit in evidence.items()},
        }
        planning_evidence = {
            "artwork": metadata, "WHY": base["WHY"], "WHAT": profile["what"], "HOW": profile["how"],
            "units": [
                {"unit_ref": ref, "role": "core" if ref in core_refs else "supporting", **unit}
                for ref, unit in evidence.items()
            ],
        }
        instruction = f"{DOCENT_PROMPT}\n\n{HOW_FOCUS[profile['how']]}\n\n{STRATEGY_GENERATION_RULES}"
        if cases is not None:
            comparisons = await run_automatic_cases(
                gemini, model, instruction, base, planning_evidence, evidence, core_refs, profile, cases,
            )
            return {
                "mode": "automatic", "artwork": metadata, "artwork_id": artwork["id"],
                "published_unit_count": len(available), "evidence_by_ref": evidence,
                "prompts": {"strategy": AUTOMATIC_PROMPT, "generation": instruction},
                "comparisons": comparisons,
            }
        comparisons = []
        for condition, context in CONDITIONS.items():
            brief, action = VIEWING_BRIEFS[condition]
            plan_input = {**planning_evidence, "CONTEXT": context or None,
                          "viewing_hypothesis": brief, "proposed_viewing_action": action}
            strategy, strategy_model = await gemini.generate(model, STRATEGY_PROMPT, plan_input, ExplanationStrategy)
            strategy.context_connection = action
            try:
                validate_strategy(strategy, evidence, core_refs, bool(context))
            except ValueError as error:
                raise ValueError(f"Invalid strategy for {condition}: {error}; observation ref "
                                 f"{strategy.observation_unit_ref}, links "
                                 f"{[link.unit_ref for link in strategy.evidence_links]}") from error
            plan = strategy.model_dump(mode="json")
            plan["boundaries"] = list(BOUNDARIES)
            generation_input = {**base, "explanation_strategy": plan}
            # Only the grounded viewing instructions reach generation, not the personal account.
            result, generation_model = await gemini.generate(model, instruction, generation_input, DocentText)
            for reported, candidates in (
                (result.used_core_unit_ids, core), (result.used_supporting_unit_ids, supporting),
            ):
                ids = {UUID(unit["id"]) for unit in candidates}
                if len(set(reported)) != len(reported) or not set(reported) <= ids:
                    raise ValueError("Generation reported an ID outside the fixed evidence roles")
            if not result.used_core_unit_ids:
                raise ValueError("Generation reported no Core evidence")
            comparisons.append({
                "condition": condition, "profile": {**profile, "context": context},
                "viewing_hypothesis": brief,
                "explanation_strategy": plan, "strategy_model": strategy_model,
                "after": {
                    "text": result.text, "core_units": core, "supporting_units": supporting,
                    "debug": {**result.model_dump(mode="json", exclude={"text"}), "model": generation_model},
                },
            })
            print(f"Generated {condition}", flush=True)
        return {
            "artwork": metadata, "artwork_id": artwork["id"], "published_unit_count": len(available),
            "evidence_by_ref": evidence, "prompts": {"strategy": STRATEGY_PROMPT, "generation": instruction},
            "comparisons": comparisons,
        }


async def run_automatic_cases(gemini, model, instruction, base, planning_evidence, evidence, core_refs,
                              profile, cases):
    comparisons = []
    baseline = None
    core = base["core_units"]
    supporting = base["supporting_units"]
    for case in cases:
        for repetition in range(1, case.repeats + 1):
            record = {
                "condition": case.name, "repetition": repetition,
                "profile": {**profile, "context": case.context},
            }
            stage = "strategy"
            try:
                strategy, version = await generate_automatic(
                    gemini, model, AUTOMATIC_PROMPT,
                    {**planning_evidence, "CONTEXT": case.context or None}, AutomaticStrategy,
                )
                record["explanation_strategy"] = strategy.model_dump(mode="json")
                record["strategy_model"] = version
                validate_automatic_strategy(strategy, evidence, core_refs, case.context)
                plan = strategy.model_dump(mode="json", exclude={"connection_rationale"})
                plan["boundaries"] = list(dict.fromkeys([*plan["boundaries"], *BOUNDARIES]))
                if not case.context and baseline is None:
                    baseline = plan
                if strategy.connection_type == "NONE" and baseline is not None:
                    plan = baseline
                record["applied_strategy"] = plan
                stage = "generation"
                result, version = await generate_automatic(
                    gemini, model, instruction, {**base, "explanation_strategy": plan}, DocentText,
                )
                record["after"] = {
                    "text": result.text, "core_units": core, "supporting_units": supporting,
                    "debug": {**result.model_dump(mode="json", exclude={"text"}), "model": version},
                }
                for reported, candidates in (
                    (result.used_core_unit_ids, core), (result.used_supporting_unit_ids, supporting),
                ):
                    ids = {UUID(unit["id"]) for unit in candidates}
                    if len(set(reported)) != len(reported) or not set(reported) <= ids:
                        raise ValueError("Generation reported an ID outside its fixed evidence role")
                if not result.used_core_unit_ids:
                    raise ValueError("Generation reported no Core evidence")
            except (HTTPException, ValueError) as error:
                record["error"] = {"stage": stage, "message": str(error)}
                print(f"{case.name} {repetition}: {stage} failed: {error}", flush=True)
            else:
                print(f"{case.name} {repetition}: {strategy.connection_type}", flush=True)
            comparisons.append(record)
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--core", nargs="+", type=UUID, required=True)
    parser.add_argument("--support", nargs="*", type=UUID, default=[])
    parser.add_argument("--contexts", type=Path, help="JSON list of free-text cases for automatic mode")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    cases = None
    if args.contexts:
        cases = [ContextCase.model_validate(row) for row in json.loads(args.contexts.read_text(encoding="utf-8"))]
        if not cases or cases[0].context or len({case.name for case in cases}) != len(cases):
            parser.error("contexts must begin with an empty baseline and use unique case names")
    result = asyncio.run(run_experiment(snapshot, list(map(str, args.core)), list(map(str, args.support)), cases))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
