import json
import unittest
from types import SimpleNamespace
from uuid import UUID

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.docent import (
    DOCENT_PROMPT,
    HOW_FOCUS,
    SERVICE_DOCENT_RULES,
    SERVICE_HOW_FOCUS,
    WHY_GUIDANCE,
    WHY_PERSONALIZATION_GUIDANCE,
)
from app.docent_strategy import (
    AUTOMATIC_PROMPT,
    CONTENT_RULES,
    DOCENT_PLANNING_RULES,
    SERVICE_CONTENT_RULES,
    SERVICE_DOCENT_PLANNING_RULES,
    SERVICE_STRATEGY_GENERATION_RULES,
    STRATEGY_GENERATION_RULES,
)
from app.visitor import PublishedUnit, visitor_router


ARTWORK_ID = UUID(int=21)
EXHIBITION_ID = UUID(int=20)
CORE = PublishedUnit(
    id=UUID(int=1),
    category="MEANING",
    content="정물과 인물이 함께 등장합니다.",
)


class ServicePromptRulesTest(unittest.TestCase):
    def test_service_guidance_covers_each_why_and_how_without_rewriting_baseline(self):
        self.assertEqual(set(WHY_PERSONALIZATION_GUIDANCE), {"discover", "relax", "reflect", "together"})
        for guidance in WHY_PERSONALIZATION_GUIDANCE.values():
            for label in ("목적:", "전개:", "관람 행동:", "구분:"):
                self.assertIn(label, guidance)
        self.assertNotEqual(WHY_GUIDANCE["discover"], WHY_PERSONALIZATION_GUIDANCE["discover"])
        self.assertIn("Supporting보다 우선", SERVICE_DOCENT_RULES)
        self.assertIn("evidence_insufficient를 true로 표시", SERVICE_DOCENT_RULES)
        self.assertIn("전문용어", SERVICE_HOW_FOCUS["Basic"])
        self.assertIn("관계를 분석", SERVICE_HOW_FOCUS["Advanced"])
        self.assertNotIn("450–750", HOW_FOCUS["Basic"])
        self.assertNotIn("700–1,100", HOW_FOCUS["Advanced"])
        self.assertIn("설명하세요", DOCENT_PROMPT)

    def test_strategy_addenda_preserve_baseline_prompt_composition(self):
        self.assertIn("이 실험의 explanation_strategy", STRATEGY_GENERATION_RULES)
        self.assertIn("required_content가 주어집니다", CONTENT_RULES)
        self.assertIn("모든 Core는 최소 한 개념", DOCENT_PLANNING_RULES)
        self.assertIn("네 WHY의 목적", SERVICE_DOCENT_PLANNING_RULES)
        self.assertIn("evidence_insufficient를 true로 표시", SERVICE_CONTENT_RULES)
        self.assertIn("WHY의 목적", SERVICE_STRATEGY_GENERATION_RULES)
        self.assertIn("viewing_hypothesis", AUTOMATIC_PROMPT)


class ServicePromptRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_why_how_profiles_reach_strategy_and_generation(self):
        artwork = {
            "id": str(ARTWORK_ID),
            "name": "Example",
            "artist": "Artist",
            "year": "1939",
            "exhibition": {"id": str(EXHIBITION_ID), "name": "Example"},
            "units": [CORE.model_dump(mode="json")],
        }
        strategy = {
            "connection_type": "NONE",
            "connection_rationale": "No visitor context.",
            "observation_focus": "함께 등장하는 정물과 인물",
            "observation_unit_ref": 1,
            "interpretation_angle": "정물과 인물의 관계",
            "evidence_links": [{"unit_ref": 1, "role_in_explanation": "Core claim"}],
            "narrative_flow": ["관찰 단서 살피기", "Core 내용 설명하기"],
            "context_connection": None,
            "boundaries": ["작가 의도는 추정하지 않음"],
            "required_content": [{"core_refs": [1], "concept": CORE.content}],
            "observation_quote": CORE.content,
        }
        generated = {
            "text": "정물과 인물이 함께 등장하는 점을 살펴보세요.",
            "used_core_unit_ids": [str(CORE.id)],
            "used_supporting_unit_ids": [],
            "evidence_insufficient": False,
        }
        provider_requests = []

        def upstream(request):
            if request.url.path.endswith("/visitor_artwork"):
                return httpx.Response(200, json=artwork)
            provider_requests.append(json.loads(request.content))
            title = provider_requests[-1]["generationConfig"]["responseJsonSchema"]["title"]
            payload = strategy if title == "DocentStrategyPlan" else generated
            return httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps(payload)}]},
            }]})

        config = SimpleNamespace(
            visitor_docent_unit_limit=6,
            visitor_docent_review_artwork_ids=[],
            app_env="test",
            visitor_docent_debug=False,
            visitor_docent_strategy_enabled=True,
            gemini_docent_model="",
            gemini_model="test-model",
            gemini_api_key=SecretStr("mock-only"),
            supabase_url="https://catalog.example",
            supabase_publishable_key=SecretStr("mock-only"),
        )
        app = FastAPI()
        app.include_router(visitor_router(lambda: config))

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as provider:
            app.state.http = provider
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                for why, guidance in WHY_PERSONALIZATION_GUIDANCE.items():
                    for how in HOW_FOCUS:
                        start = len(provider_requests)
                        response = await client.post(
                            f"/api/visitor/exhibitions/{EXHIBITION_ID}/artworks/{ARTWORK_ID}/docent",
                            json={"why": why, "what": "MEANING", "how": how, "context": ""},
                        )

                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"text": generated["text"]})
                        self.assertEqual(len(provider_requests) - start, 2)
                        plan_request, generation_request = provider_requests[start:]
                        plan_input = json.loads(plan_request["contents"][0]["parts"][0]["text"])
                        generation_input = json.loads(
                            generation_request["contents"][0]["parts"][0]["text"]
                        )
                        self.assertEqual(plan_input["WHY"], guidance)
                        self.assertEqual(plan_input["HOW"], how)
                        self.assertEqual(generation_input["WHY"], guidance)
                        self.assertEqual(generation_input["HOW"], how)
                        self.assertIn(
                            SERVICE_DOCENT_PLANNING_RULES,
                            plan_request["systemInstruction"]["parts"][0]["text"],
                        )
                        generation_instruction = generation_request["systemInstruction"]["parts"][0]["text"]
                        self.assertIn(SERVICE_DOCENT_RULES, generation_instruction)
                        self.assertIn(SERVICE_HOW_FOCUS[how], generation_instruction)
                        self.assertIn(SERVICE_STRATEGY_GENERATION_RULES, generation_instruction)
                        self.assertIn(SERVICE_CONTENT_RULES, generation_instruction)
                        self.assertIn(CONTENT_RULES, generation_instruction)
                        self.assertIn(STRATEGY_GENERATION_RULES, generation_instruction)
