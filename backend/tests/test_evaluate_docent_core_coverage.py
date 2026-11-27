import csv
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from app.docent import EvidencePlan, UnitSelection
from app.evaluate_docent_core_coverage import evaluate_plan_application


@dataclass(frozen=True)
class Candidate:
    id: str
    category: str
    content: str


class CoreCoverageEvaluationTest(unittest.TestCase):
    columns = [
        "artwork_id", "artwork_name", "what_category", "core_unit_id", "core_content",
        "essential_label", "semantic_aspect", "redundancy_group", "review_reason",
        "review_status",
    ]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.review_csv = Path(self.temp.name) / "coverage.csv"
        self.units = {
            "required-a": Candidate("required-a", "VISUAL", "A required visual fact."),
            "required-b": Candidate("required-b", "VISUAL", "A second required visual fact."),
            "optional": Candidate("optional", "VISUAL", "An optional visual fact."),
            "review": Candidate("review", "VISUAL", "An unconfirmed visual fact."),
            "support": Candidate("support", "BACKGROUND", "A supporting fact."),
        }
        review_rows = [
            ("required-a", "A required visual fact.", "REQUIRED", "aspect-a", "shared"),
            ("required-b", "A second required visual fact.", "REQUIRED", "aspect-b", "shared"),
            ("optional", "An optional visual fact.", "OPTIONAL", "aspect-c", "optional-group"),
            ("review", "An unconfirmed visual fact.", "REVIEW_NEEDED", "aspect-d", "review-group"),
        ]
        with self.review_csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.columns)
            writer.writeheader()
            for unit_id, content, label, aspect, group in review_rows:
                writer.writerow({
                    "artwork_id": "art-1",
                    "artwork_name": "Example artwork",
                    "what_category": "VISUAL",
                    "core_unit_id": unit_id,
                    "core_content": content,
                    "essential_label": label,
                    "semantic_aspect": aspect,
                    "redundancy_group": group,
                    "review_reason": "PENDING",
                    "review_status": "PROPOSED_REVIEW",
                })
        self.candidates = {
            ref: self.units[unit_id]
            for ref, unit_id in enumerate(self.units, start=1)
        }
        self.fallback = UnitSelection(
            core=[self.units["required-a"], self.units["required-b"]],
        )

    def evaluate(self, core_refs, *, limit=6, fallback=None):
        return evaluate_plan_application(
            self.review_csv,
            "VISUAL",
            self.candidates,
            limit,
            fallback or self.fallback,
            EvidencePlan(core_refs=core_refs, links=[]),
        )

    def test_all_required_core_units_are_covered_and_other_labels_stay_separate(self):
        result = self.evaluate([1, 2])

        self.assertTrue(result.plan_applied)
        self.assertEqual(result.metrics["required_coverage"], {
            "covered": 2, "required": 2, "ratio": 1.0,
        })
        self.assertEqual(result.metrics["missing_required_ids"], [])
        self.assertEqual(result.metrics["optional_missing_ids"], ["optional"])
        self.assertEqual(result.metrics["review_needed_core_ids"], ["review"])
        self.assertEqual(result.metrics["review_needed_selected_ids"], [])
        self.assertEqual(
            result.metrics["selected_redundancy_groups"]["shared"],
            ["required-a", "required-b"],
        )

    def test_partial_plan_reports_required_omission_without_claiming_service_rejection(self):
        result = self.evaluate([1])

        self.assertTrue(result.plan_applied)
        self.assertEqual(result.metrics["missing_required_ids"], ["required-b"])
        self.assertEqual(
            result.metrics["missing_required_reasons"],
            {"required-b": "omitted_by_plan"},
        )
        self.assertEqual(result.metrics["plan_application"], "semantic")

    def test_duplicate_core_reference_is_reported_and_application_deduplicates_it(self):
        result = self.evaluate([1, 1, 2])

        self.assertTrue(result.plan_applied)
        self.assertEqual(
            result.metrics["duplicate_plan_refs"],
            [{"ref": 1, "core_unit_id": "required-a"}],
        )
        self.assertEqual(result.metrics["duplicate_selected_core_ids"], [])
        self.assertEqual(result.metrics["required_coverage"]["ratio"], 1.0)

    def test_valid_and_unknown_references_apply_valid_partial_plan(self):
        result = self.evaluate([1, 999])

        self.assertTrue(result.plan_applied)
        self.assertEqual(
            result.metrics["invalid_plan_refs"],
            [{"ref": 999, "reason": "unknown_reference"}],
        )
        self.assertEqual(result.metrics["missing_required_ids"], ["required-b"])
        self.assertEqual(result.metrics["plan_application"], "semantic")

    def test_no_valid_core_reference_uses_local_fallback(self):
        fallback = UnitSelection(core=[self.units["required-a"], self.units["required-b"]])
        result = self.evaluate([999], fallback=fallback)

        self.assertFalse(result.plan_applied)
        self.assertIs(result.selection, fallback)
        self.assertEqual(result.metrics["plan_application"], "local_fallback")
        self.assertEqual(result.metrics["invalid_plan_refs"][0]["reason"], "unknown_reference")
        self.assertEqual(result.metrics["required_coverage"]["ratio"], 1.0)

    def test_required_core_dropped_by_plan_unit_budget_is_distinguished(self):
        result = self.evaluate([1, 3, 2], limit=2)

        self.assertTrue(result.plan_applied)
        self.assertEqual(
            [unit.id for unit in result.selection.core],
            ["required-a", "optional"],
        )
        self.assertEqual(result.metrics["missing_required_ids"], ["required-b"])
        self.assertEqual(result.metrics["unit_limit_excluded_core_ids"], ["required-b"])
        self.assertEqual(
            result.metrics["missing_required_reasons"],
            {"required-b": "unit_limit"},
        )

    def test_fallback_unit_limit_miss_is_distinguished(self):
        fallback = UnitSelection(
            core=[self.units["required-a"]],
            excluded={self.units["required-b"].id: "selection_limit"},
        )
        result = self.evaluate([999], fallback=fallback)

        self.assertFalse(result.plan_applied)
        self.assertEqual(
            result.metrics["missing_required_reasons"],
            {"required-b": "fallback_unit_limit"},
        )

    def test_category_mismatch_reference_is_reported(self):
        result = self.evaluate([1, 5])

        self.assertTrue(result.plan_applied)
        self.assertEqual(
            result.metrics["invalid_plan_refs"],
            [{
                "ref": 5,
                "core_unit_id": "support",
                "reason": "category_mismatch",
            }],
        )

    def test_required_core_with_wrong_category_reference_is_not_counted_as_covered(self):
        wrong_category_candidates = {
            1: self.units["required-a"],
            2: Candidate("required-b", "BACKGROUND", "A second required visual fact."),
        }
        result = evaluate_plan_application(
            self.review_csv,
            "VISUAL",
            wrong_category_candidates,
            6,
            self.fallback,
            EvidencePlan(core_refs=[1, 2], links=[]),
        )

        self.assertTrue(result.plan_applied)
        self.assertEqual(result.metrics["missing_required_ids"], ["required-b"])
        self.assertEqual(
            result.metrics["missing_required_reasons"],
            {"required-b": "invalid_category_reference"},
        )


if __name__ == "__main__":
    unittest.main()
