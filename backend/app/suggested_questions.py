import re
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, StringConstraints

from .gemini_units import Gemini
from .schemas import Category, RequestBody


QuestionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class SuggestedQuestion(RequestBody):
    question: QuestionText
    category: Category
    related_unit_ids: list[UUID] = Field(min_length=1, max_length=2)


class SuggestedQuestionPool(RequestBody):
    questions: list[SuggestedQuestion] = Field(max_length=8)


SUGGESTED_QUESTIONS_PROMPT = """Generate natural Korean follow-up questions for this specific museum artwork.
Use ONLY the provided artwork metadata and published Content Units.
Every question must be answerable from the provided Units.
Do not introduce outside knowledge, and do not infer intention, cause, reason, symbolism, or relationships unless explicitly supported.
Each question should explore one main curiosity and avoid joining separate information needs with unnecessary "and".
Every question must be specific to the artwork and natural for an actual museum visitor.
Prefer observational, explanatory, or interpretive questions over simple factual recall.
Each question should encourage further exploration.
Assign category from the main information needed: VISUAL, MEANING, TECHNIQUE, or BACKGROUND.
related_unit_ids must contain only real Unit IDs that directly support the answer, preferably one or two Units.
Do not invent Unit IDs. If evidence is insufficient for a category, omit questions for that category.
Returning fewer than eight questions is better than unsupported questions.
Generate approximately 6 to 8 questions when sufficient evidence exists."""


def _duplicate_key(question):
    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", question.casefold())
    return text


async def generate_suggested_questions(gemini: Gemini, model: str, artwork, units):
    if not units:
        return []
    source_units = [
        {"id": str(unit.id), "category": unit.category, "content": unit.content}
        for unit in units
    ]
    output, _ = await gemini.generate(
        model,
        SUGGESTED_QUESTIONS_PROMPT,
        {"artwork": artwork, "units": source_units},
        SuggestedQuestionPool,
    )
    valid_ids = {unit.id for unit in units}
    seen = set()
    valid = []
    for item in output.questions:
        if not item.related_unit_ids:
            continue
        if any(unit_id not in valid_ids for unit_id in item.related_unit_ids):
            continue
        key = _duplicate_key(item.question)
        if len(key) < 4 or key in seen:
            continue
        if any(key in existing or existing in key for existing in seen):
            continue
        seen.add(key)
        valid.append(item)
    return valid
