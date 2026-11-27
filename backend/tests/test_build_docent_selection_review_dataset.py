import csv
import tempfile
import unittest
from pathlib import Path

from app.build_docent_selection_review_dataset import (
    ReviewUnit,
    build_review_rows,
    write_review_csv,
)
from app.docent_csv_input import load_approved_what_csv


class ReviewDatasetBuilderTest(unittest.TestCase):
    def test_builds_every_core_candidate_pair_with_pending_labels(self):
        artwork = {"id": "art-1", "name": "Example artwork", "artist": ""}
        units = [
            ReviewUnit("core-v", "A red circle is visible.", "VISUAL"),
            ReviewUnit("core-m", "The circle suggests unity.", "MEANING"),
            ReviewUnit("core-t", "The circle is painted with oil.", "TECHNIQUE"),
            ReviewUnit("core-b", "The artist made the circle in 1900.", "BACKGROUND"),
        ]

        rows = build_review_rows(artwork, units)

        self.assertEqual(len(rows), 12)
        self.assertEqual(
            {row["what_category"] for row in rows},
            {"VISUAL", "MEANING", "TECHNIQUE", "BACKGROUND"},
        )
        self.assertTrue(all(row["relevance_label"] == "PENDING" for row in rows))
        self.assertTrue(all(row["relation_type"] == "PENDING" for row in rows))
        self.assertTrue(all(row["review_reason"] == "PENDING" for row in rows))
        self.assertEqual(rows[0]["core_unit_id"], "core-v")
        self.assertEqual(rows[0]["core_content"], units[0].content)

    def test_global_selection_ranks_across_all_cores_and_keeps_source_order_ties(self):
        artwork = {"id": "art-2", "name": "Example artwork", "artist": ""}
        units = [
            ReviewUnit("core-1", "gloves open book", "MEANING"),
            ReviewUnit("core-2", "artist humor friendship", "MEANING"),
            ReviewUnit("support-1", "gloves open book cover", "VISUAL"),
            ReviewUnit("support-2", "book gloves open beside cover", "TECHNIQUE"),
            ReviewUnit("support-3", "humor friendship artist group", "BACKGROUND"),
        ]

        rows = build_review_rows(artwork, units)
        selected = {
            row["supporting_unit_id"]
            for row in rows
            if row["what_category"] == "MEANING" and row["improved_global_selected"] == "true"
        }
        ranks = {
            row["supporting_unit_id"]: row["improved_global_rank"]
            for row in rows if row["what_category"] == "MEANING"
        }

        self.assertEqual(selected, {"support-1", "support-2"})
        self.assertEqual(ranks["support-1"], 1)
        self.assertEqual(ranks["support-2"], 2)
        self.assertEqual(ranks["support-3"], 3)
        self.assertEqual(len(selected), 2)

    def test_legacy_and_improved_scores_are_both_recorded(self):
        artwork = {"id": "art-4", "name": "Example artwork", "artist": ""}
        units = [
            ReviewUnit(
                "core", "The cover by Mary Reynolds displays a pair of gloves.", "MEANING",
            ),
            ReviewUnit(
                "support", "Mary Reynolds placed the gloves on a cover.", "VISUAL",
            ),
        ]

        rows = [
            row for row in build_review_rows(artwork, units)
            if row["what_category"] == "MEANING"
        ]

        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["legacy_pair_score"], rows[0]["improved_pair_score"])
        self.assertEqual(rows[0]["improved_pair_overlap_terms"], "cover|gloves")

    def test_write_refuses_to_overwrite_an_existing_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review.csv"
            output.write_text("keep this file", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_review_csv(output, [])
            self.assertEqual(output.read_text(encoding="utf-8"), "keep this file")

    def test_shared_csv_loader_filters_approved_keep_and_preserves_source_fields(self):
        source_rows = [
            {
                "artwork_id": "art-3", "artwork_title": "Source title",
                "unit_id": "art-3_CU01", "text": "Core source text.",
                "gold_category": "MEANING", "human_approval": "APPROVED",
                "new_action": "KEEP",
            },
            {
                "artwork_id": "art-3", "artwork_title": "Source title",
                "unit_id": "art-3_CU02", "text": "Split proposal.",
                "gold_category": "VISUAL", "human_approval": "APPROVED",
                "new_action": "SPLIT",
            },
            {
                "artwork_id": "art-3", "artwork_title": "Source title",
                "unit_id": "art-3_CU03", "text": "Pending proposal.",
                "gold_category": "TECHNIQUE", "human_approval": "PENDING",
                "new_action": "KEEP",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "approved.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=source_rows[0].keys())
                writer.writeheader()
                writer.writerows(source_rows)

            record = load_approved_what_csv(path, "art-3")

        self.assertEqual(record["artwork"]["id"], "art-3")
        self.assertEqual(record["artwork"]["name"], "Source title")
        self.assertEqual(record["units"], [{
            "id": "art-3_CU01",
            "content": "Core source text.",
            "category": "MEANING",
        }])
        self.assertEqual(
            record["source_metadata"]["publication_status"],
            "not present in source; not asserted",
        )


if __name__ == "__main__":
    unittest.main()
