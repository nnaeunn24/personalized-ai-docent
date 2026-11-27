"""Offline prompt comparisons for WHY/HOW personalization; never calls a model."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .docent import DOCENT_PROMPT, HOW_FOCUS, WHY_GUIDANCE
from .docent_strategy import (
    AUTOMATIC_PROMPT,
    CONTENT_RULES,
    DOCENT_PLANNING_RULES,
    STRATEGY_GENERATION_RULES,
)


WHY_EXPERIMENT_GUIDANCE = {
    "discover": """목적: 작품에서 새로 알게 되는 구체적 사실이나 관계를 발견하게 하세요.
전개: 근거가 있는 관찰 단서 하나에서 시작해, 그 단서가 알려 주는 사실을 설명하고 WHAT의 핵심으로 연결하세요.
행동: 관람객이 그 단서를 살펴보고 설명된 관계를 다시 확인하게 안내하세요.
구분: 흥미로운 배경 지식을 덧붙이는 것보다 '무엇을 새로 알게 되는가'를 중심에 두세요. 근거 없는 놀라움이나 사실을 만들지 마세요.""",
    "relax": """목적: 부담 없이 작품을 천천히 살펴보게 하세요.
전개: 한 관찰 지점에서 시작해, 자료가 뒷받침하는 다음 지점이나 세부로 부드럽게 이동하세요. 시선 이동이 WHAT의 설명을 돕게 하세요.
행동: 한 대상을 살핀 뒤 다음 대상으로 천천히 시선을 옮기도록 제안하세요. 위치 관계가 불확실하면 이동 경로를 만들지 마세요.
구분: 차분한 속도와 부담 없는 관찰을 중심에 두고, 퀴즈나 정답을 요구하지 마세요.""",
    "reflect": """목적: 작품의 관찰에서 출발해 근거에 기반한 생각거리나 해석 가능성을 여세요.
전개: 구체적 단서, 그 단서가 허용하는 가능한 읽기, 그 읽기를 지지하는 근거와 한계를 연결하세요.
행동: 관람객이 단서와 해석의 연결을 다시 살펴보거나 열린 질문을 생각해 보게 하세요. 답을 강요하지 마세요.
구분: 관람객의 개인 경험이나 감정을 추정하지 말고, 발견한 사실만 전달하거나 동행자와의 대화를 필수로 요구하지 마세요.""",
    "together": """목적: 함께 작품을 볼 때 서로 다른 관찰을 나눌 수 있는 지점을 제공하세요.
전개: 함께 볼 수 있는 구체적 단서에서 시작해, 근거가 있는 관점이나 대비를 제시하고 WHAT의 핵심으로 연결하세요.
행동: 가능하면 각자 같은 단서를 살펴보거나 서로 다른 시선을 비교해 보도록 선택적으로 제안하세요.
구분: 실제 동행자나 대화를 가정하거나 강요하지 마세요. 함께 볼 관찰과 관점의 차이가 핵심이며, 단순히 친근한 말투만 쓰는 것으로 대신하지 마세요.""",
}

HOW_EXPERIMENT_GUIDANCE = {
    "Basic": """대상: 쉬운 일상 언어로 핵심과 관찰 단서를 충분히 설명하세요. 전문용어가 필요하면 처음 나올 때 짧게 뜻을 설명하세요.
깊이와 Core: 문장을 쉽게 바꾸되 필수 Core 개념과 관계를 생략하거나 바꾸지 마세요. 단순히 이름만 언급하지 말고 이해에 필요한 설명을 유지하세요.
Supporting: Core를 더 쉽게 이해시키는 구체적 단서나 설명에만 사용하세요. 반복하거나 개수를 채우기 위해 넣지 마세요.
분량 실험 가설: 450–750자, 약 5–8문장을 참고 목표로 삼되 확정 규칙으로 취급하지 마세요. 이 범위를 맞추기 위해 Core를 생략하거나 설명을 억지로 줄이지 마세요.""",
    "Advanced": """대상: 정확한 용어와 복합 문장을 허용하되 논리 연결을 분명히 하세요. 핵심 용어는 필요한 만큼 정의하고, 어려운 용어의 나열을 깊이로 보지 마세요.
깊이와 Core: 필수 Core 개념과 관계를 모두 유지하세요. 서로 다른 근거가 제공되는 경우 관찰과 기법·표현 효과·가능한 해석의 관계를 분석하세요. 두 근거를 단순 나열하는 데 그치지 마세요.
Supporting: Core 간 관계, 기법 효과 또는 필요한 맥락을 실제로 설명할 때만 사용하세요. Core를 반복하거나 새 사실을 추가하는 용도로 쓰지 마세요.
분량 실험 가설: 700–1,100자, 약 6–10문장을 참고 목표로 삼되 확정 규칙으로 취급하지 마세요. 범위 달성을 위해 Core Coverage나 근거 충실도를 낮추지 마세요.""",
}

STRATEGY_EXPERIMENT_ADDENDUM = """WHY와 HOW는 설명 전략에 반영하되, WHAT의 의미나 선택된 evidence를 바꾸지 마세요.
전략은 선택된 Core와 Supporting을 그대로 사용하고, 새 Unit·사실·관계·작가 의도를 만들지 마세요.
WHY에 맞는 첫 관찰, 비교·시선 이동, WHAT으로의 연결을 계획하세요. 관람객의 상황이나 감정을 추정하지 말고, 화면 자료가 뒷받침하는 행동만 제안하세요.
Basic은 핵심 관계를 쉽게 풀고 필요한 전문용어를 설명하는 전개를 우선하세요. Advanced는 근거가 허용할 때 서로 다른 근거 사이의 관계를 계획하되, Core 개념을 누락하거나 대체하지 마세요.
길이 실험 범위는 계획의 필수 제약이 아닙니다. 모든 선택 Core가 필수 개념 계획에 반영되는 기존 규칙을 유지하세요."""

GENERATION_EXPERIMENT_ADDENDUM = """WHY와 HOW는 본문 전반의 관찰 초점과 정보 전개에 반영하세요. profile 입력에 있는 WHY 안내는 목표를 설명하는 자료이지, 그대로 되풀이할 문구가 아닙니다.
선택된 Core와 Supporting, supporting_links 및 required_content를 그대로 사용하세요. 필수 Core 개념을 줄이거나 Supporting을 의무적으로 추가하지 마세요. 분량 목표보다 Core 보존과 근거 충실도를 우선하세요.
관찰 행동, 위치, 형태, 인과, 상징, 작가 의도는 제공 근거가 뒷받침하는 범위에서만 설명하세요. 사실과 가능한 해석을 구분하고, 관람객의 동행·경험·감정을 추정하지 마세요."""


@dataclass(frozen=True)
class PromptComparison:
    why: str
    how: str
    generation_input: dict[str, Any]
    strategy_input: dict[str, Any] | None
    baseline_generation_instruction: str
    improved_generation_instruction: str
    baseline_strategy_instruction: str | None
    improved_strategy_instruction: str | None


def _unit_list(source: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    units = source.get(field)
    if not isinstance(units, list) or any(not isinstance(unit, dict) for unit in units):
        raise ValueError(f"{field} must be a list of Unit objects.")
    return units


def _strategy_input(source: Mapping[str, Any]) -> dict[str, Any]:
    core_units = _unit_list(source, "core_units")
    supporting_units = _unit_list(source, "supporting_units")
    strategy_source = {
        key: deepcopy(source[key])
        for key in ("artwork", "WHY", "WHAT", "HOW")
        if key in source
    }
    strategy_source["CONTEXT"] = deepcopy(source.get("CONTEXT"))
    strategy_source["units"] = [
        {
            **deepcopy(unit),
            "unit_ref": ref,
            "role": "core" if ref <= len(core_units) else "supporting",
        }
        for ref, unit in enumerate(core_units + supporting_units, start=1)
    ]
    return strategy_source


def build_prompt_comparisons(
    source: Mapping[str, Any], *, strategy_applied: bool = True,
) -> list[PromptComparison]:
    """Build paired baseline/improved prompts for all 4 WHY x 2 HOW profiles."""
    core_units = _unit_list(source, "core_units")
    _unit_list(source, "supporting_units")
    if strategy_applied and not core_units:
        raise ValueError("Strategy prompts require at least one selected Core Unit.")

    comparisons = []
    for why, why_guidance in WHY_GUIDANCE.items():
        for how, how_focus in HOW_FOCUS.items():
            generation_input = deepcopy(dict(source))
            generation_input["WHY"] = why_guidance
            generation_input["HOW"] = how

            baseline_generation = f"{DOCENT_PROMPT}\n\n{how_focus}"
            baseline_strategy = None
            strategy_input = None
            if strategy_applied:
                baseline_generation = (
                    f"{baseline_generation}\n\n{STRATEGY_GENERATION_RULES}\n\n{CONTENT_RULES}"
                )
                baseline_strategy = f"{AUTOMATIC_PROMPT}\n\n{DOCENT_PLANNING_RULES}"
                strategy_input = _strategy_input(generation_input)

            improved_generation = (
                f"{baseline_generation}\n\n"
                f"{WHY_EXPERIMENT_GUIDANCE[why]}\n\n"
                f"{HOW_EXPERIMENT_GUIDANCE[how]}\n\n"
                f"{GENERATION_EXPERIMENT_ADDENDUM}"
            )
            improved_strategy = (
                f"{baseline_strategy}\n\n{STRATEGY_EXPERIMENT_ADDENDUM}"
                if baseline_strategy is not None
                else None
            )
            comparisons.append(PromptComparison(
                why=why,
                how=how,
                generation_input=generation_input,
                strategy_input=strategy_input,
                baseline_generation_instruction=baseline_generation,
                improved_generation_instruction=improved_generation,
                baseline_strategy_instruction=baseline_strategy,
                improved_strategy_instruction=improved_strategy,
            ))
    return comparisons
