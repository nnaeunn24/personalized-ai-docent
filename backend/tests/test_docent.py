import json
import unittest
from types import SimpleNamespace
from uuid import UUID

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.docent import DEFAULT_DOCENT_REVIEW_ARTWORK_IDS, EvidencePlan, apply_evidence_plan, select_units
from app.visitor import PublishedUnit, visitor_router


ARTWORK = {"name": "Example", "artist": "Artist", "year": "1939"}


def unit(number, category, content):
    return PublishedUnit(id=UUID(int=number), category=category, content=content)


class SelectionTest(unittest.TestCase):
    def test_adds_related_support_and_excludes_unrelated_and_duplicates(self):
        core = unit(1, "MEANING", "인물의 자세는 긴장감을 준다.")
        support = unit(2, "VISUAL", "인물의 자세가 서로 대조된다.")
        irrelevant = unit(3, "BACKGROUND", "미술관이 1939년에 소장했다.")
        duplicate = unit(4, "BACKGROUND", "인물의  자세는 긴장감을 준다.")
        result = select_units([duplicate, core, irrelevant, support], "MEANING", 6, ARTWORK)
        self.assertEqual(result.core, [core])
        self.assertEqual(result.supporting, [support])
        self.assertEqual(result.excluded, {duplicate.id: "duplicate", irrelevant.id: "low_relevance"})

    def test_reserves_room_for_support_with_multiple_core_candidates(self):
        core = [unit(i, "MEANING", f"인물의 자세는 단서 {i}를 보여 준다.") for i in range(1, 5)]
        support = unit(5, "VISUAL", "인물의 자세가 서로 대조된다.")
        result = select_units([*core, support], "MEANING", 3, ARTWORK)
        self.assertEqual(result.core, core[:2])
        self.assertEqual(result.supporting, [support])

    def test_no_matching_units_use_only_support(self):
        units = [unit(i, "MEANING", str(i)) for i in range(1, 4)]
        result = select_units(units, "VISUAL", 6, ARTWORK)
        self.assertEqual(result.core, [])
        self.assertEqual(result.supporting, units[:2])

    def test_plan_keeps_anchors_and_drops_excess_or_duplicate_links(self):
        units = [
            unit(1, "MEANING", "First claim"),
            unit(2, "MEANING", "Anchored claim"),
            unit(3, "VISUAL", "Visible clue"),
            unit(4, "BACKGROUND", "Background fact"),
        ]
        plan = EvidencePlan.model_validate({
            "core_refs": [1, 2],
            "links": [
                {"core_ref": 2, "supporting_ref": 99, "relation": "visual_evidence"},
                {"core_ref": 2, "supporting_ref": 3, "relation": "visual_evidence"},
                {"core_ref": 1, "supporting_ref": 3, "relation": "visual_evidence"},
                {"core_ref": 1, "supporting_ref": 4, "relation": "interpretive_context"},
            ],
        })
        fallback = select_units(units, "MEANING", 2, ARTWORK)
        result = apply_evidence_plan(dict(enumerate(units, 1)), "MEANING", 2, fallback, plan)
        self.assertEqual(result.core, [units[1]])
        self.assertEqual(result.supporting, [units[2]])


class DocentRouteTest(unittest.IsolatedAsyncioTestCase):
    async def request_docent(self, units, generated=None, *, needs_review=False, what="MEANING", plan=None,
                             how="Basic", strategy_enabled=False, strategy_plan=None, assessment=None,
                             debug=True, context=""):
        artwork_id = UUID(DEFAULT_DOCENT_REVIEW_ARTWORK_IDS[0]) if needs_review else UUID(int=21)
        exhibition_id = UUID(int=20)
        provider_requests = []

        def upstream(request):
            if request.url.path.endswith("/visitor_artwork"):
                return httpx.Response(200, json={
                    **ARTWORK, "id": str(artwork_id),
                    "exhibition": {"id": str(exhibition_id), "name": "Example"},
                    "units": [row.model_dump(mode="json") for row in units],
                })
            provider_requests.append(request)
            payload = json.loads(request.content)
            title = payload["generationConfig"]["responseJsonSchema"]["title"]
            fixture = {"EvidencePlan": plan, "DocentStrategyPlan": strategy_plan,
                       "DocentStrategyAssessment": assessment}
            if title in fixture:
                if fixture[title] is None:
                    return httpx.Response(502)
                response_text = json.dumps(fixture[title])
            else:
                response_text = generated
            return httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": response_text}]},
            }]})

        config = SimpleNamespace(
            visitor_docent_unit_limit=6,
            visitor_docent_review_artwork_ids=[UUID(DEFAULT_DOCENT_REVIEW_ARTWORK_IDS[0])],
            visitor_docent_debug=debug, visitor_docent_strategy_enabled=strategy_enabled,
            gemini_docent_model="", gemini_model="test-model",
            gemini_api_key=SecretStr("test"), supabase_url="https://catalog.example",
            supabase_publishable_key=SecretStr("test"),
        )
        app = FastAPI()
        app.include_router(visitor_router(lambda: config))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as provider:
            app.state.http = provider
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                result = await client.post(
                    f"/api/visitor/exhibitions/{exhibition_id}/artworks/{artwork_id}/docent",
                    json={"why": "discover", "what": what, "how": how, "context": context},
                )
        return result, provider_requests

    def strategy_fixture(self, connection_type="NONE"):
        action = None if connection_type == "NONE" else "먼저 인물의 자세를 보고 주변 사물로 시선을 옮깁니다."
        return {
            "connection_type": connection_type,
            "connection_rationale": "실험 근거를 검토함",
            "observation_focus": "정물에 포함된 인물의 자세",
            "observation_unit_ref": 1,
            "observation_quote": "정물과 인물이 함께 등장합니다.",
            "interpretation_angle": "정물과 인물을 함께 보는 관점",
            "evidence_links": [{"unit_ref": 1, "role_in_explanation": "핵심 의미"}],
            "narrative_flow": ["인물 관찰", "정물의 의미 설명"],
            "context_connection": action,
            "boundaries": ["작가 의도는 추정하지 않음"],
            "required_content": [{"core_refs": [1], "concept": "정물과 인물이 함께 등장합니다."}],
        }

    async def test_default_path_retains_legacy_payload_and_no_strategy_debug(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "인물과 정물을 함께 살펴보세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        response, calls = await self.request_docent([core], generated, context="천천히 보고 싶어요.")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("strategy_details", response.json()["debug"])
        self.assertEqual(len(calls), 1)
        payload = json.loads(json.loads(calls[0].content)["contents"][0]["parts"][0]["text"])
        self.assertEqual(payload["CONTEXT"], "천천히 보고 싶어요.")
        self.assertNotIn("required_content", payload)

    async def test_strategy_plan_generation_and_assessment_never_repair(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        support = unit(2, "VISUAL", "인물의 자세가 대조됩니다.")
        generated = json.dumps({"text": "정물의 인물에 주목하세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        semantic_plan = {"core_refs": [1], "links": [
            {"core_ref": 1, "supporting_ref": 2, "relation": "visual_evidence"},
        ]}
        assessment = {"required_content": [{"content_id": 1, "present": True}], "observation_action": False,
                      "observation_action_grounded": True}
        response, calls = await self.request_docent(
            [core, support], generated, plan=semantic_plan, strategy_enabled=True,
            strategy_plan=self.strategy_fixture("INDIRECT"), assessment=assessment,
            context="천천히 보고 싶어요.", how="Advanced",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "정물의 인물에 주목하세요.")
        requests = [json.loads(call.content) for call in calls]
        self.assertEqual([row["generationConfig"]["responseJsonSchema"]["title"] for row in requests],
                         ["EvidencePlan", "DocentStrategyPlan", "DocentText", "DocentStrategyAssessment"])
        _, planner, writer, verifier = [json.loads(row["contents"][0]["parts"][0]["text"]) for row in requests]
        self.assertEqual(planner["CONTEXT"], "천천히 보고 싶어요.")
        self.assertEqual(planner["HOW"], "Advanced")
        self.assertEqual(writer["required_content"][0]["core_unit_ids"], [str(core.id)])
        self.assertEqual(writer["supporting_units"][0]["id"], str(support.id))
        self.assertEqual(writer["required_observation_action"], writer["explanation_strategy"]["context_connection"])
        self.assertNotIn("CONTEXT", writer)
        self.assertNotIn("CONTEXT", verifier)
        self.assertNotIn("connection_rationale", writer["explanation_strategy"])
        details = response.json()["debug"]["strategy_details"]
        self.assertEqual(details["status"], "applied")
        self.assertFalse(details["assessment"]["observation_action"])
        self.assertTrue(details["assessment"]["observation_action_grounded"])

    async def test_strategy_without_context_or_debug_has_no_assessment_call(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "인물과 정물을 함께 살펴보세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        for context in ("", "숫자 1234"):
            response, calls = await self.request_docent(
                [core], generated, strategy_enabled=True, strategy_plan=self.strategy_fixture(),
                debug=False, context=context,
            )
            self.assertEqual(response.json(), {"text": "인물과 정물을 함께 살펴보세요."})
            self.assertEqual(len(calls), 2)
            payload = json.loads(json.loads(calls[-1].content)["contents"][0]["parts"][0]["text"])
            self.assertIsNone(payload["required_observation_action"])
            self.assertEqual(payload["explanation_strategy"]["connection_type"], "NONE")

    async def test_invalid_required_core_reference_falls_back_without_raw_context(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "인물과 정물을 함께 살펴보세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        plan = self.strategy_fixture("DIRECT")
        plan["required_content"][0]["core_refs"] = [2]
        response, calls = await self.request_docent(
            [core], generated, strategy_enabled=True, strategy_plan=plan, context="천천히 보고 싶어요.",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["debug"]["strategy_details"]["status"], "planning_fallback")
        self.assertEqual(len(calls), 2)
        payload = json.loads(json.loads(calls[-1].content)["contents"][0]["parts"][0]["text"])
        self.assertNotIn("CONTEXT", payload)
        self.assertNotIn("required_content", payload)

    async def test_invalid_observation_quote_falls_back(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "인물과 정물을 함께 살펴보세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        plan = self.strategy_fixture()
        plan["observation_quote"] = "인물의 오른쪽에 화분이 있습니다."
        result, calls = await self.request_docent([core], generated, strategy_enabled=True, strategy_plan=plan)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["debug"]["strategy_details"]["status"], "planning_fallback")
        self.assertEqual(len(calls), 2)

    async def test_assessment_failure_keeps_generated_text(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        answer = "인물과 정물을 함께 살펴보세요."
        generated = json.dumps({"text": answer, "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        result, calls = await self.request_docent(
            [core], generated, strategy_enabled=True, strategy_plan=self.strategy_fixture(),
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["text"], answer)
        self.assertIsNone(result.json()["debug"]["strategy_details"]["assessment"])
        self.assertEqual(len(calls), 3)

    async def test_strategy_with_no_core_retains_existing_support_fallback(self):
        support = unit(2, "VISUAL", "인물의 자세가 대조됩니다.")
        generated = json.dumps({"text": "인물의 자세를 비교해 보세요.", "used_core_unit_ids": [],
                                "used_supporting_unit_ids": [str(support.id)], "evidence_insufficient": True})
        result, calls = await self.request_docent([support], generated, strategy_enabled=True, context="천천히")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["debug"]["evidence_insufficient"])
        self.assertEqual(result.json()["debug"]["strategy_details"]["status"], "no_core")
        self.assertEqual(len(calls), 1)

    async def test_empty_and_reviewed_out_catalog_skip_generation(self):
        for units, needs_review in [([], False), ([unit(1, "MEANING", "근거")], True)]:
            result, calls = await self.request_docent(units, needs_review=needs_review)
            self.assertEqual(result.status_code, 200)
            self.assertIsNone(result.json()["text"])
            self.assertTrue(result.json()["debug"]["evidence_insufficient"])
            self.assertEqual(calls, [])
            if needs_review:
                self.assertEqual(result.json()["debug"]["excluded_units"][0]["reason"], "artwork_needs_review")

    async def test_short_text_is_returned_with_valid_roles_and_no_retry(self):
        core = unit(1, "MEANING", "인물의 자세는 긴장감을 준다.")
        support = unit(2, "VISUAL", "인물의 자세가 서로 대조된다.")
        answer = "두 인물의 자세가 대비됩니다."
        generated = json.dumps({
            "text": answer, "used_core_unit_ids": [str(core.id)],
            "used_supporting_unit_ids": [str(support.id)], "evidence_insufficient": False,
        })
        result, calls = await self.request_docent([core, support], generated)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(calls), 2)
        payload = json.loads(json.loads(calls[-1].content)["contents"][0]["parts"][0]["text"])
        self.assertEqual(payload["core_units"][0]["id"], str(core.id))
        self.assertEqual(payload["supporting_units"][0]["id"], str(support.id))
        debug = result.json()["debug"]
        self.assertEqual(debug["used_core_unit_ids"], [str(core.id)])
        self.assertEqual(debug["used_supporting_unit_ids"], [str(support.id)])
        self.assertEqual(debug["sentence_count"], 1)
        self.assertEqual(debug["character_count"], len(answer))
        self.assertEqual(debug["selection_strategy"], "lexical_fallback")

    async def test_semantic_support_connects_different_wording(self):
        core = unit(1, "MEANING", "Person-like shapes make the tabletop read as an inhabited scene.")
        support = unit(2, "VISUAL", "A sculptural figure appears beside the geranium.")
        unrelated = unit(3, "BACKGROUND", "The museum obtained it in 1932.")
        link = {"core_id": str(core.id), "supporting_id": str(support.id), "relation": "visual_evidence"}
        plan = {"core_refs": [1], "links": [
            {"core_ref": 1, "supporting_ref": 2, "relation": "visual_evidence"},
        ]}
        generated = json.dumps({
            "text": "화분 곁의 조각상 때문에 사람이 있는 장면처럼 읽힙니다.",
            "used_core_unit_ids": [str(core.id)],
            "used_supporting_unit_ids": [str(support.id)], "evidence_insufficient": False,
        })
        result, calls = await self.request_docent([core, support, unrelated], generated, plan=plan, how="Advanced")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(calls), 2)
        plan_request = json.loads(json.loads(calls[0].content)["contents"][0]["parts"][0]["text"])
        self.assertEqual(plan_request["HOW"], "Advanced")
        generation_request = json.loads(calls[-1].content)
        self.assertIn("이어받은 점과 달라진 점", generation_request["systemInstruction"]["parts"][0]["text"])
        payload = json.loads(generation_request["contents"][0]["parts"][0]["text"])
        self.assertEqual(payload["supporting_links"], [link])
        self.assertEqual(payload["supporting_units"][0]["id"], str(support.id))
        debug = result.json()["debug"]
        self.assertEqual(debug["selection_strategy"], "semantic")
        self.assertEqual(debug["excluded_units"][0]["reason"], "semantic_not_selected")

    async def test_invalid_evidence_plan_falls_back_to_local_selection(self):
        core = unit(1, "MEANING", "인물의 자세는 긴장감을 준다.")
        support = unit(2, "VISUAL", "인물의 자세가 서로 대조된다.")
        invalid = {"core_refs": [2], "links": []}
        generated = json.dumps({
            "text": "인물의 자세에 주목해 보세요.",
            "used_core_unit_ids": [str(core.id)], "used_supporting_unit_ids": [],
            "evidence_insufficient": False,
        })
        result, calls = await self.request_docent([core, support], generated, plan=invalid)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.json()["debug"]["selection_strategy"], "lexical_fallback")

    async def test_rejects_mislabeled_evidence_id(self):
        support = unit(1, "VISUAL", "근거")
        generated = json.dumps({
            "text": "설명입니다.", "used_core_unit_ids": [str(support.id)],
            "used_supporting_unit_ids": [], "evidence_insufficient": False,
        })
        result, calls = await self.request_docent([support], generated)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(len(calls), 1)
