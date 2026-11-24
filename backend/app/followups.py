from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, Field

from .ai_settings import PromptBody, PromptVersion
from .artwork_questions import AnswerText
from .docent import HOW_FOCUS
from .schemas import Category, RequestBody, Review
from .suggested_questions import QuestionText, SUGGESTED_QUESTIONS_PROMPT, _duplicate_key


HowLevel = Literal["Basic", "Advanced"]
ReviewState = Literal["pending", "reviewed", "published"]
HOW_LEVELS = ("Basic", "Advanced")


class Answers(RequestBody):
    Basic: AnswerText
    Advanced: AnswerText


class FollowupEdit(Review):
    question: QuestionText
    category: Category
    related_unit_ids: list[UUID] = Field(min_length=1, max_length=8)
    priority: int = Field(ge=1, le=100)
    answers_by_how: dict[HowLevel, AnswerText]


class GeneratedQuestion(RequestBody):
    question: QuestionText
    category: Category
    related_unit_ids: list[UUID] = Field(min_length=1, max_length=8)
    priority: int = Field(ge=1, le=100)
    answers_by_how: Answers


class GeneratedAnswers(RequestBody):
    id: UUID
    answers_by_how: Answers


class GeneratedPool(RequestBody):
    questions: list[GeneratedQuestion] = Field(max_length=8)
    existing_answers: list[GeneratedAnswers] = Field(max_length=50)


class GenerateFollowups(RequestBody):
    category: Category | None = None
    question_id: UUID | None = None
    replace: bool = False


class ReviewFollowups(RequestBody):
    items: dict[UUID, AwareDatetime] = Field(min_length=1, max_length=100)
    status: ReviewState


class FollowupPromptTest(RequestBody):
    artwork_id: UUID
    unit_ids: list[UUID] = Field(min_length=1, max_length=200)
    body: PromptBody
    version: PromptVersion | None = None


class VisitorFollowup(RequestBody):
    question_id: UUID
    question: QuestionText
    category: Category
    priority: int
    answer: AnswerText


INSTRUCTIONS = SUGGESTED_QUESTIONS_PROMPT.replace("published Content Units", "reviewed or published Content Units") + """
Write both answers in natural Korean. Both must use the same linked Unit IDs, never unlinked Units.
For Basic, explain the core in everyday language and explain necessary specialist terms immediately.
For Advanced, deepen the explanation by connecting observations, technique, effect or context where supported.
Do not make unsupported causal or historical claims. Basic is about accessibility, not just length.
The requested category limits are maxima. Within each category, use lower priority numbers for stronger questions.
Do not repeat existing questions or rephrase the same curiosity. For existing_answers, return only requested IDs
and answer the exact saved question using only its linked Units. Return empty arrays for inapplicable work.
"""


def generation_units(units):
    return [{"id": unit["id"], "number": unit["number"], "category": unit["category"], "content": unit["content"],
             "status": unit["status"]} for unit in units if unit["status"] in ("reviewed", "published")]


def complete(row):
    return all(row["answers_by_how"].get(level, "").strip() for level in HOW_LEVELS)


def evidence_available(row, unit_ids):
    return bool(row["related_unit_ids"]) and set(row["related_unit_ids"]) <= unit_ids


async def generate_followups(gemini, model, prompt, artwork, units, existing, limits, answer_targets):
    if not units or (not any(limits.values()) and not answer_targets):
        return [], model
    by_id = {unit["id"]: unit for unit in units}
    output, actual_model = await gemini.generate(
        model, f"{INSTRUCTIONS}\n\nCurator instructions:\n{prompt}",
        {"artwork": {key: artwork[key] for key in ("name", "artist", "year")},
         "units": units, "question_limits": limits, "HOW": HOW_FOCUS,
         "existing_questions": [{"question": row["question"], "category": row["category"]} for row in existing],
         "answer_targets": [{key: row[key] for key in ("id", "question", "category", "related_unit_ids")} for row in answer_targets]},
        GeneratedPool,
    )
    seen = [_duplicate_key(row["question"]) for row in existing]
    priorities = {category: {row["priority"] for row in existing if row["category"] == category}
                  for category in limits}
    remaining = limits.copy()
    rows = []
    for question in sorted(output.questions, key=lambda item: item.priority):
        key = _duplicate_key(question.question)
        ids = list(dict.fromkeys(map(str, question.related_unit_ids)))
        if (not remaining.get(question.category) or len(key) < 4 or any(unit_id not in by_id for unit_id in ids)
                or not any(by_id[unit_id]["category"] == question.category for unit_id in ids)
                or any(key == prior or key in prior or prior in key or SequenceMatcher(None, key, prior).ratio() >= .87
                       for prior in seen if prior)):
            continue
        priority = next((value for value in range(1, 101) if value not in priorities[question.category]), None)
        if priority is None:
            continue
        priorities[question.category].add(priority)
        seen.append(key)
        remaining[question.category] -= 1
        rows.append({**question.model_dump(mode="json"), "related_unit_ids": ids, "priority": priority})

    targets = {row["id"]: row for row in answer_targets}
    for item in output.existing_answers:
        item_id = str(item.id)
        target = targets.pop(item_id, None)
        if target:
            generated = item.answers_by_how.model_dump()
            if not target.get("replace_answers"):
                generated.update({level: answer for level, answer in target["answers_by_how"].items() if answer.strip()})
            rows.append({"id": item_id, "answers_by_how": generated})
    if targets:
        raise HTTPException(502, "일부 기존 질문의 답변을 생성하지 못했습니다. 기존 질문은 유지됩니다.")
    return rows, actual_model
