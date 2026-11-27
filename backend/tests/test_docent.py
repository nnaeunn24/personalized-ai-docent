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

    def test_local_supplement_does_not_displace_core(self):
        core = [unit(i, "MEANING", f"인물의 자세는 단서 {i}를 보여 준다.") for i in range(1, 4)]
        support = unit(5, "VISUAL", "인물의 자세가 서로 대조된다.")
        result = select_units([*core, support], "MEANING", 3, ARTWORK)
        self.assertEqual(result.core, core)
        self.assertEqual(result.supporting, [])

    def test_no_matching_units_use_only_support(self):
        units = [unit(i, "MEANING", str(i)) for i in range(1, 4)]
        result = select_units(units, "VISUAL", 6, ARTWORK)
        self.assertEqual(result.core, [])
        self.assertEqual(result.supporting, units[:2])

    def apply_plan(self, units, limit, core_refs, *, links=(), assessments=(), why="discover", how="Basic",
                   what="MEANING"):
        plan = EvidencePlan.model_validate({
            "core_refs": core_refs, "links": list(links), "core_assessments": list(assessments),
        })
        fallback = select_units(units, what, limit, ARTWORK, why=why, how=how)
        return apply_evidence_plan({row.id.int: row for row in units}, what, limit, fallback, plan, ARTWORK,
                                   why=why, how=how)

    def test_what_reverses_roles_for_the_same_units(self):
        meaning = unit(1, "MEANING", "색면의 충돌이 정물을 회화적 실험으로 바꾼다.")
        technique = unit(2, "TECHNIQUE", "붓질을 끊어 붉은색과 초록색을 나란히 쌓았다.")
        for core, support in ((meaning, technique), (technique, meaning)):
            link = {
                "core_ref": core.id.int, "supporting_ref": support.id.int,
                "core_quote": core.content, "supporting_quote": support.content,
                "connection": "나란히 쌓은 보색이 화면에서 충돌하는 방식과 그 효과를 함께 설명한다.",
            }
            result = self.apply_plan([meaning, technique], 2, [core.id.int], links=[link], what=core.category)
            self.assertEqual(result.core, [core])
            self.assertEqual(result.supporting, [support])

    def test_bridge_counts_once_and_next_support_covers_another_core(self):
        calm = unit(1, "MEANING", "화면 위쪽은 차분하게 읽힌다.")
        weight = unit(2, "MEANING", "화면 아래쪽은 무게감을 준다.")
        figures = unit(3, "MEANING", "인물상이 정물의 장르 경계를 흐린다.")
        bridge = unit(4, "VISUAL", "위쪽의 밝은 여백과 아래쪽의 밀집한 어두운 물체가 대비된다.")
        closeup = unit(5, "VISUAL", "위쪽에 연한 분홍색이 둥근 얼룩 형태로 남아 있다.")
        posture = unit(6, "VISUAL", "접시 옆에 앞으로 몸을 구부린 인물상이 그려져 있다.")
        links = [
            {"core_ref": core.id.int, "supporting_ref": support.id.int, "core_quote": core.content,
             "supporting_quote": support.content, "connection": connection, "observation_whys": whys}
            for core, support, connection, whys in (
                (calm, bridge, "위쪽 여백과 아래쪽 밀도의 대비로 위쪽의 차분함을 설명한다.", []),
                (weight, bridge, "밝은 여백과 비교하면 아래쪽의 어두운 밀집이 주는 무게가 드러난다.", []),
                (calm, closeup, "연한 색을 차분하게 읽는 관찰 지점을 제시한다.", ["discover"]),
                (figures, posture, "사물 곁에서 사람의 자세를 함께 읽는 근거다.", []),
            )
        ]
        # Personalization cannot admit a proposal whose quoted evidence is absent.
        links.append({**links[-1], "supporting_ref": 5, "observation_whys": ["discover"]})
        units = [calm, weight, figures, bridge, closeup, posture]
        result = self.apply_plan(units, 5, [1, 2, 3], links=links)
        self.assertEqual(result.core, [calm, weight, figures])
        self.assertEqual(result.supporting, [bridge, posture])
        self.assertEqual({(link.core_id, link.supporting_id) for link in result.links},
                         {(calm.id, bridge.id), (weight.id, bridge.id), (figures.id, posture.id)})

    def test_model_duplicate_collapses_and_omitted_facet_is_recovered(self):
        a = unit(1, "MEANING", "인물의 굽은 자세가 화면에 긴장감을 준다.")
        duplicate = unit(2, "MEANING", "몸을 웅크린 사람 때문에 장면이 불안해 보인다.")
        distinct = unit(3, "MEANING", "인물과 기물의 배치는 정물과 인물화의 경계를 흐린다.")
        units = [a, duplicate, distinct]
        result = self.apply_plan(units, 2, [1, 2], assessments=[
            {"ref": 1, "priority": "primary", "facets": [{"key": "posture_tension", "quote": a.content}]},
            {"ref": 2, "priority": "standard", "duplicate_of": 1,
             "duplicate_reason": "두 Unit 모두 웅크린 자세가 주는 긴장감을 설명한다.",
             "facets": [{"key": "posture_tension", "quote": duplicate.content}]},
        ])
        self.assertEqual(result.core, [a, distinct])
        self.assertEqual(result.excluded[duplicate.id], "semantic_duplicate")
        self.assertEqual(result.trace["duplicate_decisions"][0]["reason"], "same_grounded_facets")
        self.assertEqual(result.trace["added_core_ids"], [distinct.id])
        self.assertEqual(set(select_units(units, "MEANING", 3, ARTWORK).excluded), set())
        result = self.apply_plan(units, 1, [2], assessments=[{"ref": 3, "priority": "primary"}])
        self.assertEqual(result.core, [distinct])

    def test_specific_process_facets_outrank_a_recommended_general_summary(self):
        summary = unit(1, "TECHNIQUE", "Color and brushwork are important to the composition.")
        brush = unit(2, "TECHNIQUE", "Short diagonal strokes interrupt longer strokes at the upper edge.")
        layering = unit(3, "TECHNIQUE", "The painter laid down a violet underlayer before adding wet orange paint.")
        revisions = unit(4, "TECHNIQUE", "Examination revealed that a leaf was moved away from the figure.")
        rows = [(summary, "primary", "brushwork", True), (brush, "primary", "brushwork", False),
                (layering, "secondary", "layering_sequence", False), (revisions, "secondary", "revisions", False)]
        result = self.apply_plan([row[0] for row in rows], 3, [1, 2], what="TECHNIQUE", assessments=[
            {"ref": row.id.int, "priority": priority, "summary_only": is_summary,
             "facets": [{"key": key, "quote": row.content}]}
            for row, priority, key, is_summary in rows
        ])
        self.assertEqual(set(row.id for row in result.core), {brush.id, layering.id, revisions.id})
        self.assertEqual(set(result.trace["added_core_ids"]), {layering.id, revisions.id})
        self.assertIn(summary.id, result.trace["excluded_proposed_ids"])

    def test_duplicate_claim_with_distinct_anchored_facets_is_rejected(self):
        other = unit(1, "MEANING", "Broad strokes and flattened color make the familiar subject experimental.")
        figures = unit(2, "MEANING", "Arranging sculpted figures among vessels evokes an imagined landscape.")
        result = self.apply_plan([other, figures], 2, [1, 2], assessments=[
            {"ref": 1, "priority": "secondary", "duplicate_of": 2, "duplicate_reason": "Both reinvent still life.",
             "facets": [{"key": "surface_experiment", "quote": "Broad strokes and flattened color"}]},
            {"ref": 2, "priority": "primary",
             "facets": [{"key": "imagined_landscape", "quote": "evokes an imagined landscape"}]},
        ])
        self.assertEqual(result.core, [other, figures])
        self.assertEqual(result.trace["duplicate_decisions"][0]["reason"], "equivalence_not_supported")

    def test_definition_fills_an_unmet_need_and_bad_quotes_are_diagnosed(self):
        core = unit(1, "MEANING", "The composition borrows from a pastoral idyll.")
        second = unit(2, "MEANING", "The tilted figures make the scene unstable.")
        definition = unit(3, "BACKGROUND", "A pastoral idyll depicts idealized rural life.")
        visible = unit(4, "VISUAL", "The figures lean at contrasting angles.")
        extra = unit(5, "VISUAL", "The tilted figures are arranged in a row.")
        links = [
            {"core_ref": 2, "supporting_ref": 4, "need": "visual_grounding", "core_quote": second.content,
             "supporting_quote": visible.content, "contribution_key": "posture"},
            {"core_ref": 2, "supporting_ref": 5, "need": "visual_grounding", "core_quote": second.content,
             "supporting_quote": extra.content, "contribution_key": "posture"},
            {"core_ref": 1, "supporting_ref": 3, "need": "definition", "core_quote": "“Pastoral idyll”",
             "supporting_quote": "“A pastoral idyll depicts idealized rural life.”"},
        ]
        rows = [core, second, definition, visible, extra]
        result = self.apply_plan(rows, 6, [1, 2], links=links, how="Advanced")
        self.assertEqual(result.supporting[0], definition)
        self.assertIn(result.trace["supporting_proposals"][1]["reason"], ("need_already_covered", "selected"))
        self.assertEqual(result.trace["supporting_proposals"][2]["reason"], "selected")
        self.assertEqual(result.trace["unused_units"], 2)
        self.assertEqual(len(result.trace["budget_steps"]), 2)
        result = self.apply_plan(rows[:3], 6, [1, 2], links=[
            {**links[2], "supporting_quote": "A definition absent from the source."},
        ])
        self.assertEqual(result.trace["supporting_proposals"][0]["reason"], "invalid_supporting_quote")
        self.assertEqual(result.trace["unused_reason"], "no_additional_eligible_contribution")

    def test_essential_definition_replaces_only_secondary_core(self):
        core = unit(1, "MEANING", "정물에 아르카디아 풍경의 요소를 결합했다.")
        separate = unit(2, "MEANING", "붓질의 방향 차이가 정물에 움직임을 더한다.")
        summary = unit(3, "MEANING", "이 작품에는 여러 감상 방법이 있다.")
        definition = unit(4, "BACKGROUND", "아르카디아 풍경은 자연과 인물이 조화를 이루는 이상화된 장면이다.")
        units = [core, separate, summary, definition]
        assessments = [{"ref": 1, "priority": "primary"}, {"ref": 3, "priority": "secondary"}]
        link = {"core_ref": 1, "supporting_ref": 4, "relation": "interpretive_context", "need": "definition",
                "core_quote": "아르카디아 풍경의 요소", "supporting_quote": definition.content}
        for how in ("Basic", "Advanced"):
            result = self.apply_plan(units, 3, [1, 2, 3], links=[link], assessments=assessments, how=how)
            self.assertEqual(result.core, [core, separate])
            self.assertEqual(result.supporting, [definition])
        for nonessential in ({**link, "need": None}, {**link, "supporting_quote": "invented quote"}):
            result = self.apply_plan(units, 3, [1, 2, 3], links=[nonessential], assessments=assessments)
            self.assertEqual(result.core, [core, separate, summary])
            self.assertEqual(result.supporting, [])
        result = self.apply_plan(units, 2, [1, 2], links=[link], assessments=assessments)
        self.assertEqual(result.core, [core, separate])
        self.assertEqual(result.supporting, [])

    def test_local_why_ranks_observation_and_is_stable_under_reordering(self):
        core = unit(1, "MEANING", "인물의 자세는 화면에 긴장감을 준다.")
        quiet = unit(2, "VISUAL", "인물의 굽은 자세가 화면 왼쪽에 자리한다.")
        contrast = unit(3, "VISUAL", "인물의 자세가 서로 대조된다.")
        for why, expected in (("relax", quiet), ("together", contrast)):
            original = select_units([core, quiet, contrast], "MEANING", 2, ARTWORK, why=why)
            reversed_order = select_units([contrast, quiet, core], "MEANING", 2, ARTWORK, why=why)
            self.assertEqual(original.core, [core])
            self.assertEqual(original.supporting, [expected])
            self.assertEqual(original, reversed_order)

    def test_how_ranks_essential_links_without_changing_core(self):
        core = unit(1, "MEANING", "정물에 아르카디아의 구도를 빌려 왔다.")
        definition = unit(2, "BACKGROUND", "아르카디아는 목가적 이상향을 뜻한다.")
        evidence = unit(3, "VISUAL", "나무 둘레에 인물들이 느슨한 원을 이룬다.")
        links = [
            {"core_ref": 1, "supporting_ref": ref, "need": need, "relation": "direct_explanation",
             "core_quote": "아르카디아의 구도", "supporting_quote": support.content}
            for ref, need, support in ((2, "definition", definition), (3, "interpretation_grounding", evidence))
        ]
        for how, expected in (("Basic", definition), ("Advanced", evidence)):
            result = self.apply_plan([core, definition, evidence], 2, [1], links=links, how=how)
            self.assertEqual(result.core, [core])
            self.assertEqual(result.supporting, [expected])

    def test_limits_and_invalid_support_links(self):
        core = unit(1, "MEANING", "인물의 자세는 긴장감을 준다.")
        supports = [unit(i, "VISUAL", text) for i, text in enumerate([
            "인물의 자세가 서로 대조된다.", "인물의 자세는 왼쪽으로 기울었다.", "인물의 자세가 굽어 있다.",
        ], 2)]
        links = [
            {"core_ref": 99, "supporting_ref": 2, "relation": "visual_evidence"},
            {"core_ref": 1, "supporting_ref": 99, "relation": "visual_evidence"},
            {"core_ref": 1, "supporting_ref": 1, "relation": "direct_explanation"},
            *[{"core_ref": 1, "supporting_ref": i, "relation": "visual_evidence"} for i in (2, 2, 3, 4)],
        ]
        for limit in range(1, 7):
            result = self.apply_plan([core, *supports], limit, [99, 1], links=links)
            self.assertEqual(result.core, [core])
            self.assertEqual(len(set(row.id for row in result.supporting)), min(2, limit - 1))
            self.assertTrue(all(link.core_id == core.id for link in result.links))


class DocentRouteTest(unittest.IsolatedAsyncioTestCase):
    async def request_docent(self, units, generated=None, *, needs_review=False, what="MEANING", plan=None,
                             how="Basic", strategy_enabled=False, strategy_plan=None, assessment=None,
                             debug=True, context="", app_env="development", why="discover"):
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
            app_env=app_env, visitor_docent_debug=debug, visitor_docent_strategy_enabled=strategy_enabled,
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
                    json={"why": why, "what": what, "how": how, "context": context},
                )
        return result, provider_requests

    def strategy_fixture(self, connection_type="NONE"):
        citation = {"unit_ref": 1, "quote": "정물과 인물이 함께 등장합니다."}
        return {
            "central_view": {"focus": "interpretation", "focus_content_ids": [1]},
            "narrative_flow": [{
                "purpose": "observe", "delivery": "plain_explanation", "unit_refs": [1],
                "content_ids": [1], "supporting_link_refs": [],
                "observation": {"action": "notice", "evidence": [citation.copy()]},
            }],
            "connection_type": connection_type,
            "context_step": None if connection_type == "NONE" else 1,
            "connection_rationale": "실험 근거를 검토함",
            "required_content": [{"evidence": [citation]}],
        }

    async def test_disabled_flag_omits_raw_context_and_strategy_debug(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "인물과 정물을 함께 살펴보세요.", "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        response, calls = await self.request_docent([core], generated, context="천천히 보고 싶어요.")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("strategy_details", response.json()["debug"])
        self.assertEqual(len(calls), 1)
        payload = json.loads(json.loads(calls[0].content)["contents"][0]["parts"][0]["text"])
        self.assertNotIn("CONTEXT", payload)
        self.assertNotIn("required_content", payload)

    async def test_production_and_test_do_not_expose_debug_or_run_assessment(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        answer = "인물과 정물을 함께 살펴보세요."
        generated = json.dumps({"text": answer, "used_core_unit_ids": [str(core.id)],
                                "used_supporting_unit_ids": [], "evidence_insufficient": False})
        for app_env in ("production", "test"):
            response, calls = await self.request_docent(
                [core], generated, strategy_enabled=True, strategy_plan=self.strategy_fixture(),
                debug=True, app_env=app_env,
            )
            self.assertEqual(response.json(), {"text": answer})
            self.assertEqual(len(calls), 2)

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
        self.assertEqual(planner["supporting_links"], [
            {"link_ref": 1, "core_ref": 1, "supporting_ref": 2, "relation": "visual_evidence"},
        ])
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

    async def test_narrative_combines_multiple_core_concepts_with_the_selected_link(self):
        first = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        second = unit(2, "MEANING", "엇갈린 자세가 움직임을 암시합니다.")
        support = unit(3, "VISUAL", "한 인물은 앉아 있고 다른 인물은 몸을 돌립니다.")
        quote = {"unit_ref": 3, "quote": support.content}
        selection = {"core_refs": [1, 2], "links": [
            {"core_ref": 2, "supporting_ref": 3, "relation": "visual_evidence",
             "core_quote": second.content, "supporting_quote": support.content},
        ]}
        generated = json.dumps({"text": "한 인물은 앉고 다른 인물은 몸을 돌려 움직임이 느껴집니다.",
                                "used_core_unit_ids": [str(first.id), str(second.id)],
                                "used_supporting_unit_ids": [str(support.id)], "evidence_insufficient": False})
        for why, how, delivery in (("relax", "Basic", "concrete_example"),
                                    ("together", "Advanced", "relationship_analysis")):
            plan = self.strategy_fixture()
            plan["required_content"].append({"evidence": [{"unit_ref": 2, "quote": second.content}]})
            plan["central_view"]["focus_content_ids"] = [1, 2]
            plan["narrative_flow"] = [{
                "purpose": "connect", "delivery": delivery, "unit_refs": [1, 2, 3], "content_ids": [1, 2],
                "supporting_link_refs": [1], "observation": {"action": "notice", "evidence": [quote]},
            }]
            result, calls = await self.request_docent(
                [first, second, support], generated, plan=selection, strategy_enabled=True,
                strategy_plan=plan, debug=False, why=why, how=how,
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(calls), 3)
            planner, writer = [json.loads(json.loads(call.content)["contents"][0]["parts"][0]["text"])
                               for call in calls[1:]]
            self.assertEqual((planner["WHY"], planner["HOW"]), (why, how))
            self.assertTrue(planner["WHY_GUIDANCE"])
            self.assertTrue(planner["HOW_GUIDANCE"])
            self.assertEqual(planner["supporting_links"], writer["strategy_supporting_links"])
            self.assertEqual(writer["explanation_strategy"]["narrative_flow"], plan["narrative_flow"])
            self.assertEqual([row["core_unit_ids"] for row in writer["required_content"]],
                             [[str(first.id)], [str(second.id)]])

    async def test_indirect_experience_produces_only_grounded_viewing_action(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다. 인물의 시선 방향이 서로 다릅니다.")
        generated = json.dumps({"text": "두 인물의 시선 방향을 비교해 보세요.",
                                "used_core_unit_ids": [str(core.id)], "used_supporting_unit_ids": [],
                                "evidence_insufficient": False})
        context = "오랫동안 살던 곳을 떠났어요."
        plan = self.strategy_fixture("INDIRECT")
        plan["connection_rationale"] = context
        plan["narrative_flow"][0]["observation"] = {"action": "compare", "evidence": [
            {"unit_ref": 1, "quote": "정물과 인물이 함께 등장합니다."},
            {"unit_ref": 1, "quote": "인물의 시선 방향이 서로 다릅니다."},
        ]}
        for step, expected in ((1, "INDIRECT"), (99, "NONE")):
            plan["context_step"] = step
            result, calls = await self.request_docent(
                [core], generated, strategy_enabled=True, strategy_plan=plan, context=context, debug=False,
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(calls), 2)
            planner, writer = [json.loads(json.loads(call.content)["contents"][0]["parts"][0]["text"])
                               for call in calls]
            self.assertEqual(planner["CONTEXT"], context)
            self.assertNotIn(context, json.dumps(writer, ensure_ascii=False))
            self.assertEqual(writer["explanation_strategy"]["connection_type"], expected)
            if expected == "INDIRECT":
                self.assertEqual(writer["required_observation_action"]["action"], "compare")
            else:
                self.assertIsNone(writer["required_observation_action"])

    async def test_invalid_narrative_coverage_and_link_refs_use_existing_fallback(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "정물 사이에 인물이 함께 놓여 있습니다.",
                                "used_core_unit_ids": [str(core.id)], "used_supporting_unit_ids": [],
                                "evidence_insufficient": False})
        for key, value in (("content_ids", []), ("supporting_link_refs", [9])):
            plan = self.strategy_fixture()
            plan["narrative_flow"][0][key] = value
            result, calls = await self.request_docent([core], generated, strategy_enabled=True, strategy_plan=plan)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["debug"]["strategy_details"]["status"], "planning_fallback")
            self.assertEqual(len(calls), 2)

    async def test_strategy_grounds_interpretation_definition_and_revisit_in_one_flow(self):
        first = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        second = unit(2, "MEANING", "사람과 사물의 배치는 목가적 풍경을 떠올리게 합니다.")
        visual = unit(3, "VISUAL", "인물과 그릇이 가로로 번갈아 놓였습니다.")
        definition = unit(4, "BACKGROUND", "목가적 풍경은 이상화된 시골 풍경을 가리킵니다.")
        cue = {"unit_ref": 3, "quote": visual.content}
        strategy = self.strategy_fixture()
        strategy["required_content"].append({"evidence": [{"unit_ref": 2, "quote": second.content}]})
        strategy["central_view"]["focus_content_ids"] = [1, 2]
        strategy["narrative_flow"] = [
            {"purpose": "observe", "delivery": "concrete_example", "unit_refs": [3],
             "content_ids": [], "supporting_link_refs": [], "observation": {"action": "notice", "evidence": [cue]}},
            {"purpose": "connect", "delivery": "term_in_context", "unit_refs": [1, 2, 3, 4],
             "content_ids": [1, 2], "supporting_link_refs": [1, 2], "observation": None,
             "bridges": [
                 {"purpose": "observation_to_interpretation", "content_id": 1, "evidence": cue},
                 {"purpose": "just_in_time", "content_id": 2, "evidence": {"unit_ref": 4, "quote": definition.content}},
             ],
             "analogy": {"focus": "relationships", "content_id": 1, "evidence": cue}},
            {"purpose": "reflect", "delivery": "relationship_analysis", "unit_refs": [3],
             "content_ids": [], "supporting_link_refs": [], "observation": {"action": "revisit", "evidence": [cue]},
             "revisit": {"earlier_step": 1, "content_id": 2}},
        ]
        selection = {"core_refs": [1, 2], "links": [
            {"core_ref": 1, "supporting_ref": 3, "relation": "visual_evidence",
             "need": "visual_grounding",
             "core_quote": first.content, "supporting_quote": visual.content},
            {"core_ref": 2, "supporting_ref": 4, "relation": "interpretive_context",
             "core_quote": second.content, "supporting_quote": definition.content},
        ]}
        generated = json.dumps({"text": "인물과 그릇이 번갈아 놓인 모습을 보세요.",
                                "used_core_unit_ids": [str(first.id)], "used_supporting_unit_ids": [],
                                "evidence_insufficient": False})
        for invalid in (None, "wrong_link", "invented_fact", "wrong_revisit"):
            step = strategy["narrative_flow"][1]
            step["supporting_link_refs"] = [1] if invalid == "wrong_link" else [1, 2]
            step["bridges"][0]["evidence"] = (
                {**cue, "quote": "인물이 오른쪽 위에 있습니다."} if invalid == "invented_fact" else cue
            )
            strategy["narrative_flow"][2]["revisit"]["earlier_step"] = 2 if invalid == "wrong_revisit" else 1
            result, calls = await self.request_docent(
                [first, second, visual, definition], generated, plan=selection,
                strategy_enabled=True, strategy_plan=strategy, app_env="production",
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(calls), 3)
            writer = json.loads(json.loads(calls[-1].content)["contents"][0]["parts"][0]["text"])
            if invalid:
                self.assertNotIn("explanation_strategy", writer)
            else:
                flow = writer["explanation_strategy"]["narrative_flow"]
                self.assertEqual(flow, strategy["narrative_flow"])
                self.assertEqual(flow[1]["content_ids"], [1, 2])

    async def test_context_lens_without_observation_uses_selected_evidence_and_safe_hint(self):
        core = unit(1, "MEANING", "정물과 인물이 함께 등장합니다.")
        generated = json.dumps({"text": "정물과 인물의 관계에 주목해 보세요.",
                                "used_core_unit_ids": [str(core.id)], "used_supporting_unit_ids": [],
                                "evidence_insufficient": False})
        context = "여행 준비 중이고 연락처는 010-1234-5678입니다."
        plan = self.strategy_fixture("INDIRECT")
        plan["narrative_flow"][0]["observation"] = None
        plan["connection_rationale"] = context
        plan["context_lens"] = {"mode": "analogy", "focus": "relationships", "content_id": 1,
                                "situation_hint": "preparation",
                                "evidence": {"unit_ref": 1, "quote": core.content}}
        for mode, invalid in (("analogy", None), ("perspective", None), ("emphasis", "quote"),
                              ("perspective", "content")):
            lens = plan["context_lens"]
            lens["mode"] = mode
            lens["content_id"] = 9 if invalid == "content" else 1
            lens["evidence"]["quote"] = "작가가 여행을 기록했습니다." if invalid == "quote" else core.content
            result, calls = await self.request_docent(
                [core], generated, strategy_enabled=True, strategy_plan=plan, context=context, debug=False,
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(calls), 2)
            planner, writer = [json.loads(json.loads(call.content)["contents"][0]["parts"][0]["text"])
                               for call in calls]
            self.assertEqual(planner["CONTEXT"], context)
            self.assertNotIn("010-1234-5678", json.dumps(writer, ensure_ascii=False))
            self.assertIsNone(writer["required_observation_action"])
            strategy = writer["explanation_strategy"]
            if invalid:
                self.assertEqual(strategy["connection_type"], "NONE")
                self.assertNotIn("context_lens", strategy)
            else:
                self.assertEqual(strategy["connection_type"], "INDIRECT")
                self.assertEqual(strategy["context_lens"]["mode"], mode)
                self.assertEqual(strategy["context_lens"]["situation_hint"], "무언가를 준비할 때")

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
        plan["required_content"][0]["evidence"][0]["unit_ref"] = 2
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
        plan["narrative_flow"][0]["observation"]["evidence"][0]["quote"] = "인물의 오른쪽에 화분이 있습니다."
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
            {"core_ref": 1, "supporting_ref": 2, "relation": "visual_evidence",
             "core_quote": "Person-like shapes", "supporting_quote": "A sculptural figure"},
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
        self.assertEqual(plan_request["WHY"], "discover")
        self.assertNotIn("CONTEXT", plan_request)
        generation_request = json.loads(calls[-1].content)
        payload = json.loads(generation_request["contents"][0]["parts"][0]["text"])
        self.assertIn("이어받은 점과 달라진 점", payload["HOW_GUIDANCE"])
        self.assertEqual(payload["supporting_links"], [link])
        self.assertEqual(payload["supporting_units"][0]["id"], str(support.id))
        debug = result.json()["debug"]
        self.assertEqual(debug["selection_strategy"], "semantic")
        self.assertEqual(debug["excluded_units"][0]["reason"], "semantic_not_selected")
        self.assertEqual(debug["selection_details"]["proposed_core_ids"], [str(core.id)])
        self.assertEqual(debug["selection_details"]["supporting_proposals"][0]["reason"], "selected")
        reversed_result, _ = await self.request_docent([unrelated, support, core], generated, plan=plan, how="Advanced")
        self.assertEqual(result.json(), reversed_result.json())

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

        malformed = {"core_refs": [1], "links": [
            {"core_ref": 1, "supporting_ref": 2, "relation": "unsupported_relation"},
        ]}
        result, calls = await self.request_docent([core, support], generated, plan=malformed)
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
