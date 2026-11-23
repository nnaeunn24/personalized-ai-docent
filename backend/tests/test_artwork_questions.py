import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.artwork_questions import (
    NO_EVIDENCE,
    ArtworkQuestion,
    EvidenceSelection,
    GeneratedAnswer,
    answer_artwork_question,
)
from app.visitor import PublishedUnit


class ArtworkQuestionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.artwork = {"name": "데이지", "artist": "마티스", "year": "1939"}
        self.units = [
            PublishedUnit(id=uuid4(), category=category, content=content)
            for category, content in [
                ("VISUAL", "파랑과 빨강의 색면이 보입니다."),
                ("TECHNIQUE", "캔버스에 유채로 제작했습니다."),
                ("MEANING", "서로 다른 색이 화면의 균형을 이룹니다."),
                ("BACKGROUND", "니스에서 그렸습니다."),
            ]
        ]
        self.gemini = AsyncMock()

    def assessment(self, status, indexes, intent="FACTUAL"):
        return EvidenceSelection(status=status, intent=intent, unit_indexes=indexes, artwork_fields=[]), "model"

    def generated(self, indexes):
        return GeneratedAnswer(answer="파랑과 빨강을 볼 수 있어요.", used_unit_indexes=indexes), "model"

    async def ask(self, question, history=None):
        conversation = ArtworkQuestion(question=question, history=history or [])
        return await answer_artwork_question(self.gemini, "model", self.artwork, self.units, conversation)

    async def test_answerable_searches_all_categories_and_maps_real_ids(self):
        self.gemini.generate.side_effect = [self.assessment("ANSWERABLE", [0, 2]), self.generated([0])]
        answer = await self.ask("어떤 색이 보이나요?")
        selection, generation = [call.args[2] for call in self.gemini.generate.await_args_list]
        self.assertEqual(answer.answer_status, "ANSWERABLE")
        self.assertEqual(len({unit["category"] for unit in selection["units"]}), 4)
        self.assertEqual([unit["index"] for unit in generation["units"]], [0, 2])
        self.assertEqual(answer.retrieved_unit_ids, [self.units[0].id, self.units[2].id])
        self.assertEqual(answer.used_unit_ids, [self.units[0].id])

    async def test_partial_follow_up_propagates_history_and_interpretation(self):
        self.gemini.generate.side_effect = [self.assessment("PARTIAL", [0], "MIXED"), self.generated([0])]
        history = [{"question": "어떤 색이 보이나요?", "answer": "두 색이 보여요."}]
        answer = await self.ask("그 색은 어떤 느낌이고 작가는 왜 골랐나요?", history)
        self.assertEqual(answer.answer_status, "PARTIAL")
        for call in self.gemini.generate.await_args_list:
            self.assertEqual(call.args[2]["history"], history)
        self.assertEqual(self.gemini.generate.await_args.args[2]["intent"], "MIXED")

    async def test_unanswerable_skips_generation(self):
        self.gemini.generate.return_value = self.assessment("UNANSWERABLE", [])
        answer = await self.ask("이 작품의 보험료는 얼마인가요?")
        self.assertEqual((answer.answer_status, answer.answer), ("UNANSWERABLE", NO_EVIDENCE))
        self.assertEqual(answer.used_unit_ids, [])
        self.gemini.generate.assert_awaited_once()

    async def test_generation_cannot_reference_an_unselected_unit(self):
        self.gemini.generate.side_effect = [self.assessment("ANSWERABLE", [0]), self.generated([1])]
        with self.assertRaises(HTTPException) as error:
            await self.ask("어떤 색이 보이나요?")
        self.assertEqual(error.exception.status_code, 502)

    async def test_provider_error_is_reported(self):
        self.gemini.generate.side_effect = HTTPException(429, "limit")
        with self.assertRaises(HTTPException) as error:
            await self.ask("어떤 색이 보이나요?")
        self.assertEqual(error.exception.status_code, 429)

    async def test_delayed_provider_is_cancelled(self):
        async def slow_provider(*_):
            await asyncio.sleep(10)

        self.gemini.generate.side_effect = slow_provider
        short_timeout = asyncio.timeout(0.01)
        with patch("app.artwork_questions.asyncio.timeout", return_value=short_timeout):
            with self.assertRaises(HTTPException) as error:
                await self.ask("어떤 색이 보이나요?")
        self.assertEqual(error.exception.status_code, 504)
