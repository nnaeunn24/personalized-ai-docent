import unittest

from app.docent import DOCENT_PROMPT, HOW_FOCUS, WHY_GUIDANCE
from app.docent_personalization_prompt_experiment import (
    HOW_EXPERIMENT_GUIDANCE,
    WHY_EXPERIMENT_GUIDANCE,
    build_prompt_comparisons,
)
from app.docent_strategy import (
    AUTOMATIC_PROMPT,
    CONTENT_RULES,
    DOCENT_PLANNING_RULES,
    STRATEGY_GENERATION_RULES,
)


def prompt_source():
    return {
        "artwork": {"name": "Mock artwork", "artist": "Mock artist"},
        "WHY": "original WHY",
        "WHAT": "MEANING",
        "HOW": "Basic",
        "CONTEXT": None,
        "core_units": [{
            "id": "core-1", "category": "MEANING", "content": "Core source content.",
        }],
        "supporting_units": [{
            "id": "support-1", "category": "VISUAL", "content": "Supporting source content.",
        }],
        "supporting_links": [{
            "core_id": "core-1", "supporting_id": "support-1",
            "relation": "visual_evidence",
        }],
        "required_content": [{
            "content_id": 1, "core_unit_ids": ["core-1"], "concept": "Core concept.",
        }],
    }


class DocentPersonalizationPromptExperimentTest(unittest.TestCase):
    def test_builds_paired_prompts_for_all_eight_why_how_conditions(self):
        source = prompt_source()

        comparisons = build_prompt_comparisons(source)

        self.assertEqual(len(comparisons), 8)
        self.assertEqual(
            {(item.why, item.how) for item in comparisons},
            {(why, how) for why in WHY_GUIDANCE for how in HOW_FOCUS},
        )
        for item in comparisons:
            self.assertEqual(item.generation_input["WHY"], WHY_GUIDANCE[item.why])
            self.assertEqual(item.generation_input["HOW"], item.how)
            self.assertIn(WHY_EXPERIMENT_GUIDANCE[item.why], item.improved_generation_instruction)
            self.assertIn(HOW_EXPERIMENT_GUIDANCE[item.how], item.improved_generation_instruction)

    def test_baseline_matches_current_generation_and_strategy_prompt_composition(self):
        for item in build_prompt_comparisons(prompt_source()):
            expected_generation = (
                f"{DOCENT_PROMPT}\n\n{HOW_FOCUS[item.how]}\n\n"
                f"{STRATEGY_GENERATION_RULES}\n\n{CONTENT_RULES}"
            )
            expected_strategy = f"{AUTOMATIC_PROMPT}\n\n{DOCENT_PLANNING_RULES}"
            self.assertEqual(item.baseline_generation_instruction, expected_generation)
            self.assertEqual(item.baseline_strategy_instruction, expected_strategy)
            self.assertTrue(item.improved_generation_instruction.startswith(expected_generation))
            self.assertTrue(item.improved_strategy_instruction.startswith(expected_strategy))
            self.assertNotEqual(item.baseline_generation_instruction, item.improved_generation_instruction)
            self.assertNotEqual(item.baseline_strategy_instruction, item.improved_strategy_instruction)

    def test_selected_evidence_and_required_content_are_preserved(self):
        source = prompt_source()
        original = prompt_source()

        comparisons = build_prompt_comparisons(source)

        self.assertEqual(source, original)
        for item in comparisons:
            self.assertEqual(item.generation_input["core_units"], original["core_units"])
            self.assertEqual(item.generation_input["supporting_units"], original["supporting_units"])
            self.assertEqual(item.generation_input["supporting_links"], original["supporting_links"])
            self.assertEqual(item.generation_input["required_content"], original["required_content"])
            self.assertEqual(
                [unit["id"] for unit in item.strategy_input["units"]],
                ["core-1", "support-1"],
            )
            self.assertEqual(
                [unit["role"] for unit in item.strategy_input["units"]],
                ["core", "supporting"],
            )

    def test_without_applied_strategy_uses_the_service_generation_baseline(self):
        source = prompt_source()

        comparisons = build_prompt_comparisons(source, strategy_applied=False)

        self.assertEqual(len(comparisons), 8)
        for item in comparisons:
            self.assertIsNone(item.strategy_input)
            self.assertIsNone(item.baseline_strategy_instruction)
            self.assertIsNone(item.improved_strategy_instruction)
            self.assertEqual(
                item.baseline_generation_instruction,
                f"{DOCENT_PROMPT}\n\n{HOW_FOCUS[item.how]}",
            )

    def test_strategy_experiment_requires_a_selected_core(self):
        source = prompt_source()
        source["core_units"] = []

        with self.assertRaisesRegex(ValueError, "at least one selected Core"):
            build_prompt_comparisons(source)

    def test_missing_unit_lists_fail_instead_of_silently_dropping_evidence(self):
        source = prompt_source()
        del source["supporting_units"]

        with self.assertRaisesRegex(ValueError, "supporting_units"):
            build_prompt_comparisons(source)


if __name__ == "__main__":
    unittest.main()
