import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.evaluate_saved_docent_results import (
    SCHEMA_VERSION,
    compare_personalization_pairs,
    evaluate_saved_records,
    load_saved_jsonl,
    validate_saved_record,
    write_report,
)


def saved_record(
    record_id,
    *,
    origin="actual",
    why="discover",
    what="MEANING",
    how="Basic",
    text="A saved explanation.",
    role=None,
    pair_id=None,
    changed_factor=None,
    selected_core=None,
    selected_supporting=None,
    used_core=None,
    used_supporting=None,
):
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "data_origin": origin,
        "comparison": {
            "pair_id": pair_id,
            "role": role,
            "changed_factor": changed_factor,
        },
        "artwork": {"id": "art-1", "name": "Example artwork"},
        "profile": {"why": why, "what": what, "how": how},
        "selection": {
            "strategy": "semantic_plan",
            "selected_core_unit_ids": selected_core,
            "selected_supporting_unit_ids": selected_supporting,
            "core_units": [{
                "id": "core-1", "category": "MEANING", "content": "A core fact.",
            }] if selected_core else [],
            "supporting_units": [{
                "id": "support-1", "category": "VISUAL", "content": "A visual fact.",
            }] if selected_supporting else [],
        },
        "generation": {
            "status": "completed" if text else "unknown",
            "text": text,
            "model": "recorded-model",
            "requested_model": None,
            "used_core_unit_ids": used_core,
            "used_supporting_unit_ids": used_supporting,
            "evidence_insufficient": False,
        },
        "provenance": {"captured_from": "test"},
    }


class SavedDocentEvaluationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.core_review = self.directory / "core.csv"
        with self.core_review.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "artwork_id", "artwork_name", "what_category", "core_unit_id",
                "core_content", "essential_label", "semantic_aspect", "redundancy_group",
                "review_reason", "review_status",
            ])
            writer.writeheader()
            writer.writerow({
                "artwork_id": "art-1", "artwork_name": "Example artwork",
                "what_category": "MEANING", "core_unit_id": "core-1",
                "core_content": "A core fact.", "essential_label": "REQUIRED",
                "semantic_aspect": "aspect", "redundancy_group": "group",
                "review_reason": "reviewed", "review_status": "PROPOSED_REVIEW",
            })

        self.support_review = self.directory / "support.csv"
        with self.support_review.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "artwork_id", "core_unit_id", "supporting_unit_id", "relevance_label",
            ])
            writer.writeheader()
            writer.writerow({
                "artwork_id": "art-1", "core_unit_id": "core-1",
                "supporting_unit_id": "support-1", "relevance_label": "RELEVANT",
            })

    def test_reads_jsonl_and_reuses_core_and_supporting_reviews(self):
        record = saved_record(
            "run-1", selected_core=["core-1"], selected_supporting=["support-1"],
            used_core=["core-1"], used_supporting=["support-1"],
        )
        input_path = self.directory / "results.jsonl"
        input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        loaded = load_saved_jsonl(input_path)
        report = evaluate_saved_records(
            loaded, [self.core_review], [self.support_review],
        )

        evaluated = report["records"][0]
        self.assertEqual(report["dataset"]["classification"], "actual_only")
        self.assertEqual(
            evaluated["core_coverage"]["selected_core"]["required_coverage"]["ratio"],
            1.0,
        )
        self.assertEqual(
            evaluated["core_coverage"]["reported_used_core"]["required_coverage"]["ratio"],
            1.0,
        )
        self.assertEqual(
            evaluated["supporting_pair_review"]["selected_pairs"]["label_counts"]["RELEVANT"],
            1,
        )
        self.assertEqual(evaluated["groundedness"]["status"], "not_evaluated")

    def test_surface_comparison_is_limited_and_pair_validates_one_changed_factor(self):
        before = saved_record(
            "before", why="discover", text="먼저 형태를 관찰하세요.",
            role="baseline", pair_id="pair-1", changed_factor="why",
            selected_core=["core-1"], selected_supporting=["support-1"],
            used_core=["core-1"], used_supporting=["support-1"],
        )
        after = saved_record(
            "after", why="relax", text="천천히 형태를 살펴보세요.",
            role="variant", pair_id="pair-1", changed_factor="why",
            selected_core=["core-1"], selected_supporting=["support-1"],
            used_core=["core-1"], used_supporting=["support-1"],
        )

        comparison = compare_personalization_pairs([
            validate_saved_record(before, 1),
            validate_saved_record(after, 2),
        ])[0]

        self.assertEqual(comparison["status"], "surface_compared")
        self.assertEqual(comparison["changed_factor"], "why")
        self.assertFalse(comparison["surface_difference"]["exact_match_after_whitespace_normalization"])
        self.assertEqual(comparison["assessment_scope"], "actual_text_surface_difference_only")
        self.assertEqual(comparison["quality_assessment_status"], "not_semantically_assessed")

    def test_comparison_supports_what_and_how_changes(self):
        baseline = {"why": "discover", "what": "MEANING", "how": "Basic"}
        records = []
        for factor, changed_value, index in (
            ("what", "VISUAL", 1),
            ("how", "Advanced", 2),
        ):
            before = saved_record(
                f"{factor}-before", role="baseline", pair_id=f"{factor}-pair",
                changed_factor=factor, selected_core=["core-1"], selected_supporting=[],
            )
            after = saved_record(
                f"{factor}-after", role="variant", pair_id=f"{factor}-pair",
                changed_factor=factor, selected_core=["core-1"], selected_supporting=[],
            )
            before["profile"].update(baseline)
            after["profile"].update(baseline)
            after["profile"][factor] = changed_value
            records.extend([
                validate_saved_record(before, index * 2),
                validate_saved_record(after, index * 2 + 1),
            ])

        comparisons = compare_personalization_pairs(records)

        self.assertEqual(
            {item["changed_factor"] for item in comparisons},
            {"what", "how"},
        )
        self.assertTrue(all(item["status"] == "surface_compared" for item in comparisons))

    def test_mock_records_are_marked_as_structural_validation_not_quality_results(self):
        before = saved_record(
            "mock-before", origin="mock", role="baseline", pair_id="mock-pair",
            text="Mock text one.", selected_core=["core-1"], selected_supporting=[],
            used_core=["core-1"], used_supporting=[],
        )
        after = saved_record(
            "mock-after", origin="mock", why="relax", role="variant",
            pair_id="mock-pair", changed_factor="why", text="Mock text two.",
            selected_core=["core-1"], selected_supporting=[],
            used_core=["core-1"], used_supporting=[],
        )

        report = evaluate_saved_records([
            validate_saved_record(before, 1),
            validate_saved_record(after, 2),
        ])

        self.assertEqual(report["dataset"]["classification"], "mock_only")
        self.assertEqual(
            report["personalization_comparisons"][0]["assessment_scope"],
            "mock_validation_only",
        )
        self.assertEqual(
            report["personalization_comparisons"][0]["quality_assessment_status"],
            "not_semantically_assessed",
        )

    def test_unknown_values_are_allowed_but_disable_metrics_that_need_them(self):
        record = saved_record(
            "run-unknown", selected_core=None, selected_supporting=None,
            used_core=None, used_supporting=None,
        )
        record["artwork"]["id"] = "unknown"
        record["profile"]["what"] = "unknown"
        record["generation"]["model"] = "unknown"
        record["selection"]["selected_core_unit_ids"] = "unknown"
        normalized = validate_saved_record(record, 1)

        report = evaluate_saved_records([normalized], [self.core_review])

        self.assertIsNone(report["records"][0]["model"])
        self.assertEqual(
            report["records"][0]["core_coverage"]["selected_core"]["reason"],
            "no_matching_core_review_csv",
        )

    def test_rejects_completed_record_without_text_and_invalid_profile(self):
        record = saved_record("bad", text=None)
        record["generation"]["status"] = "completed"
        with self.assertRaisesRegex(ValueError, "must include text"):
            validate_saved_record(record, 1)

        record = saved_record("bad-profile")
        record["profile"]["what"] = "UNKNOWN_CATEGORY"
        with self.assertRaisesRegex(ValueError, "Invalid profile.what"):
            validate_saved_record(record, 1)

    def test_pair_rejects_more_than_one_changed_profile_field(self):
        before = saved_record(
            "before", role="baseline", pair_id="pair",
            selected_core=["core-1"], selected_supporting=[],
        )
        after = saved_record(
            "after", why="relax", role="variant", pair_id="pair",
            selected_core=["core-1"], selected_supporting=[],
        )
        after["profile"]["how"] = "Advanced"
        comparison = compare_personalization_pairs([
            validate_saved_record(before, 1),
            validate_saved_record(after, 2),
        ])[0]

        self.assertEqual(comparison["status"], "invalid_pair")
        self.assertIn("exactly one", comparison["reason"])

    def test_report_writer_preserves_output_shape_and_refuses_overwrite(self):
        path = self.directory / "report.json"
        report = evaluate_saved_records([validate_saved_record(saved_record("run-1"), 1)])

        write_report(path, report)
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["report_schema_version"], SCHEMA_VERSION)
        with self.assertRaises(FileExistsError):
            write_report(path, report)


if __name__ == "__main__":
    unittest.main()
