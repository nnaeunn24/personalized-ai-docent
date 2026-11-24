import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.followups import GeneratedPool, generate_followups
from app.visitor import visitor_router


class FollowupTest(unittest.IsolatedAsyncioTestCase):
    async def test_generation_filters_unlinked_and_duplicate_questions_and_fills_missing_answer(self):
        unit_id, unlinked_id, question_id = map(str, (uuid4(), uuid4(), uuid4()))
        saved = {
            "id": question_id, "category": "VISUAL", "question": "창문 테두리는 어떻게 보이나요?",
            "related_unit_ids": [unit_id], "priority": 1, "answers_by_how": {"Basic": "기존 검수 문장"},
        }
        answers = {"Basic": "초록색 물감이에요.", "Advanced": "초록색 안료가 창문의 경계를 강조해요."}
        valid = {
            "question": "어떤 색이 창문을 둘러싸고 있나요?", "category": "VISUAL",
            "related_unit_ids": [unit_id], "priority": 2, "answers_by_how": answers,
        }
        output = GeneratedPool.model_validate({
            "questions": [
                {**valid, "question": saved["question"], "priority": 1},
                {**valid, "related_unit_ids": [unlinked_id], "priority": 1},
                valid,
            ],
            "existing_answers": [{"id": question_id, "answers_by_how": answers}],
        })
        gemini = SimpleNamespace(generate=AsyncMock(return_value=(output, "test-model")))
        rows, _ = await generate_followups(
            gemini, "model", "curator instruction", {"name": "Study", "artist": "", "year": ""},
            [{"id": unit_id, "category": "VISUAL", "content": "초록색 안료가 창문의 경계를 그린다."}],
            [saved], {"VISUAL": 1}, [saved],
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["priority"], 2)
        self.assertEqual(rows[0]["related_unit_ids"], [unit_id])
        self.assertEqual(rows[1], {"id": question_id, "answers_by_how": {**answers, "Basic": "기존 검수 문장"}})

    async def test_visitor_recommendations_use_only_supabase_and_requested_how(self):
        artwork, exhibition, question_id = map(str, (uuid4(), uuid4(), uuid4()))
        answers = {"Basic": "저장된 쉬운 설명", "Advanced": "저장된 심화 설명"}
        called = []

        def upstream(request):
            self.assertEqual(request.url.host, "supabase.example")
            self.assertEqual(request.url.path, "/rest/v1/rpc/visitor_followup_questions")
            body = json.loads(request.content)
            called.append(body["how_level"])
            self.assertEqual((body["artwork_id"], body["exhibition_id"]), (artwork, exhibition))
            return httpx.Response(200, json=[{
                "question_id": question_id, "question": "창문은 어떤 모습인가요?", "category": "VISUAL",
                "priority": 1, "answer": answers[body["how_level"]],
            }])

        app = FastAPI()
        config = SimpleNamespace(supabase_url="https://supabase.example", supabase_publishable_key=SecretStr("test"))
        app.include_router(visitor_router(lambda: config))
        path = f"/api/visitor/exhibitions/{exhibition}/artworks/{artwork}/suggested-questions"
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as app.state.http:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                for how in answers:
                    response = await client.get(path, params={"how": how})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()[0]["answer"], answers[how])
        self.assertEqual(called, ["Basic", "Advanced"])
