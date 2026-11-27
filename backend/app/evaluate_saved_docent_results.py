"""Offline evaluation of saved docent generations; never calls a model or API."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .docent import HOW_FOCUS, WHY_GUIDANCE
from .evaluate_docent_core_coverage import (
    CoreReviewRow,
    evaluate_core_coverage,
    load_core_coverage_review,
)
from .schemas import Category


SCHEMA_VERSION = "docent-evaluation/v1"
DATA_ORIGINS = {"actual", "mock"}
GENERATION_STATUSES = {"completed", "error", "unknown"}
COMPARISON_ROLES = {"baseline", "variant"}
COMPARISON_FACTORS = {"why", "what", "how"}
SUPPORT_LABELS = {"RELEVANT", "NOT_RELEVANT", "REVIEW_NEEDED", "PENDING"}
SUPPORT_REVIEW_COLUMNS = {
    "artwork_id",
    "core_unit_id",
    "supporting_unit_id",
    "relevance_label",
}


def _require_object(value: Any, field: str, line_number: int) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object at JSONL line {line_number}.")
    return value


def _require_string(value: Any, field: str, line_number: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string at JSONL line {line_number}.")
    return value.strip()


def _nullable_text(value: Any, field: str, line_number: int) -> str | None:
    if value is None or value == "unknown":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, 'unknown', or null at JSONL line {line_number}.")
    return value.strip() or None


def _nullable_ids(value: Any, field: str, line_number: int) -> list[str] | None:
    if value is None or value == "unknown":
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be an array of non-empty strings or null at JSONL line {line_number}.")
    ids = [item.strip() for item in value]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field} contains duplicate IDs at JSONL line {line_number}.")
    return ids


def _unit_snapshot(value: Any, field: str, line_number: int) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array or null at JSONL line {line_number}.")
    normalized = []
    seen = set()
    for index, raw in enumerate(value):
        unit = _require_object(raw, f"{field}[{index}]", line_number)
        unit_id = _require_string(unit.get("id"), f"{field}[{index}].id", line_number)
        content = _require_string(unit.get("content"), f"{field}[{index}].content", line_number)
        category = _require_string(unit.get("category"), f"{field}[{index}].category", line_number).upper()
        if category not in Category.__args__:
            raise ValueError(f"Invalid {field}[{index}].category at JSONL line {line_number}: {category}")
        if unit_id in seen:
            raise ValueError(f"{field} contains duplicate Unit IDs at JSONL line {line_number}.")
        seen.add(unit_id)
        normalized.append({"id": unit_id, "content": content, "category": category})
    return normalized


def validate_saved_record(raw: Any, line_number: int) -> dict:
    record = _require_object(raw, "record", line_number)
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {SCHEMA_VERSION!r} at JSONL line {line_number}."
        )
    record_id = _require_string(record.get("record_id"), "record_id", line_number)
    data_origin = record.get("data_origin")
    if not isinstance(data_origin, str) or data_origin not in DATA_ORIGINS:
        raise ValueError(f"data_origin must be 'actual' or 'mock' at JSONL line {line_number}.")

    artwork = _require_object(record.get("artwork"), "artwork", line_number)
    artwork_id = _nullable_text(artwork.get("id"), "artwork.id", line_number)
    artwork_name = _nullable_text(artwork.get("name"), "artwork.name", line_number)

    profile = _require_object(record.get("profile"), "profile", line_number)
    normalized_profile = {}
    choices = {
        "why": set(WHY_GUIDANCE),
        "what": set(Category.__args__),
        "how": set(HOW_FOCUS),
    }
    for key, accepted in choices.items():
        if key not in profile:
            raise ValueError(f"profile.{key} is required at JSONL line {line_number}.")
        value = _nullable_text(profile[key], f"profile.{key}", line_number)
        if value is not None:
            value = value.upper() if key == "what" else value
            if value not in accepted:
                raise ValueError(f"Invalid profile.{key} at JSONL line {line_number}: {value}")
        normalized_profile[key] = value

    comparison = record.get("comparison")
    if comparison is None:
        comparison = {}
    comparison = _require_object(comparison, "comparison", line_number)
    pair_id = _nullable_text(comparison.get("pair_id"), "comparison.pair_id", line_number)
    role = _nullable_text(comparison.get("role"), "comparison.role", line_number)
    factor = _nullable_text(comparison.get("changed_factor"), "comparison.changed_factor", line_number)
    if role is not None and role not in COMPARISON_ROLES:
        raise ValueError(f"Invalid comparison.role at JSONL line {line_number}: {role}")
    if factor is not None and factor not in COMPARISON_FACTORS:
        raise ValueError(f"Invalid comparison.changed_factor at JSONL line {line_number}: {factor}")

    selection = _require_object(record.get("selection"), "selection", line_number)
    for field in ("selected_core_unit_ids", "selected_supporting_unit_ids"):
        if field not in selection:
            raise ValueError(f"selection.{field} is required at JSONL line {line_number}.")
    selected_core_ids = _nullable_ids(
        selection["selected_core_unit_ids"], "selection.selected_core_unit_ids", line_number,
    )
    selected_supporting_ids = _nullable_ids(
        selection["selected_supporting_unit_ids"], "selection.selected_supporting_unit_ids", line_number,
    )
    strategy = _nullable_text(selection.get("strategy"), "selection.strategy", line_number)
    core_units = _unit_snapshot(selection.get("core_units"), "selection.core_units", line_number)
    supporting_units = _unit_snapshot(
        selection.get("supporting_units"), "selection.supporting_units", line_number,
    )

    generation = _require_object(record.get("generation"), "generation", line_number)
    status = generation.get("status")
    if not isinstance(status, str) or status not in GENERATION_STATUSES:
        raise ValueError(f"Invalid generation.status at JSONL line {line_number}.")
    text = _nullable_text(generation.get("text"), "generation.text", line_number)
    if status == "completed" and text is None:
        raise ValueError(f"Completed generation must include text at JSONL line {line_number}.")
    model = _nullable_text(generation.get("model"), "generation.model", line_number)
    requested_model = _nullable_text(
        generation.get("requested_model"), "generation.requested_model", line_number,
    )
    used_core_ids = _nullable_ids(
        generation.get("used_core_unit_ids"), "generation.used_core_unit_ids", line_number,
    )
    used_supporting_ids = _nullable_ids(
        generation.get("used_supporting_unit_ids"), "generation.used_supporting_unit_ids", line_number,
    )
    evidence_insufficient = generation.get("evidence_insufficient")
    if evidence_insufficient is not None and not isinstance(evidence_insufficient, bool):
        raise ValueError(f"generation.evidence_insufficient must be boolean or null at JSONL line {line_number}.")

    provenance = record.get("provenance") or {}
    provenance = _require_object(provenance, "provenance", line_number)
    return {
        "record_id": record_id,
        "data_origin": data_origin,
        "comparison": {
            "pair_id": pair_id,
            "role": role,
            "changed_factor": factor,
        },
        "artwork": {"id": artwork_id, "name": artwork_name},
        "profile": normalized_profile,
        "selection": {
            "strategy": strategy,
            "selected_core_unit_ids": selected_core_ids,
            "selected_supporting_unit_ids": selected_supporting_ids,
            "core_units": core_units,
            "supporting_units": supporting_units,
        },
        "generation": {
            "status": status,
            "text": text,
            "model": model,
            "requested_model": requested_model,
            "used_core_unit_ids": used_core_ids,
            "used_supporting_unit_ids": used_supporting_ids,
            "evidence_insufficient": evidence_insufficient,
        },
        "provenance": provenance,
    }


def load_saved_jsonl(path: Path) -> list[dict]:
    records = []
    seen_ids = set()
    try:
        stream = path.open(encoding="utf-8-sig")
    except OSError as error:
        raise ValueError(f"Cannot open JSONL input: {type(error).__name__}") from None
    with stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at JSONL line {line_number}: {error.msg}") from None
            record = validate_saved_record(raw, line_number)
            if record["record_id"] in seen_ids:
                raise ValueError(f"Duplicate record_id at JSONL line {line_number}: {record['record_id']}")
            seen_ids.add(record["record_id"])
            records.append(record)
    if not records:
        raise ValueError(f"JSONL input contains no records: {path}")
    return records


def _load_core_reviews(paths: list[Path]) -> dict[str, tuple[Path, list[CoreReviewRow]]]:
    reviews = {}
    for path in paths:
        rows = load_core_coverage_review(path)
        artwork_id = rows[0].artwork_id
        if artwork_id in reviews:
            raise ValueError(f"Multiple Core Coverage CSVs supplied for artwork {artwork_id}.")
        reviews[artwork_id] = (path, rows)
    return reviews


def _load_supporting_review(path: Path) -> tuple[str, dict[tuple[str, str], str]]:
    try:
        stream = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        raise ValueError(f"Cannot open Supporting review CSV: {type(error).__name__}") from None
    with stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not SUPPORT_REVIEW_COLUMNS <= set(reader.fieldnames):
            missing = sorted(SUPPORT_REVIEW_COLUMNS - set(reader.fieldnames or ()))
            raise ValueError(f"Supporting review CSV is missing columns: {', '.join(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Supporting review CSV has no rows: {path}")
    artwork_ids = {row["artwork_id"].strip() for row in rows}
    if len(artwork_ids) != 1 or not next(iter(artwork_ids)):
        raise ValueError("Supporting review CSV must contain exactly one artwork ID.")
    pairs = {}
    for line_number, row in enumerate(rows, start=2):
        core_id = row["core_unit_id"].strip()
        supporting_id = row["supporting_unit_id"].strip()
        label = row["relevance_label"].strip().upper()
        key = (core_id, supporting_id)
        if not core_id or not supporting_id:
            raise ValueError(f"Supporting review CSV has an empty Unit ID at line {line_number}.")
        if label not in SUPPORT_LABELS:
            raise ValueError(f"Invalid relevance_label at line {line_number}: {label}")
        if key in pairs:
            raise ValueError(f"Duplicate Core/Supporting review pair at line {line_number}: {key}")
        pairs[key] = label
    return next(iter(artwork_ids)), pairs


def _coverage_for_ids(
    review_path: Path | None,
    review_rows: list[CoreReviewRow] | None,
    record: dict,
    what: str | None,
    ids: list[str] | None,
    basis: str,
) -> dict:
    if review_path is None or review_rows is None:
        return {"status": "unavailable", "reason": "no_matching_core_review_csv"}
    if what is None:
        return {"status": "unavailable", "reason": "what_is_unknown"}
    if ids is None:
        return {"status": "unavailable", "reason": "unit_ids_are_unknown"}
    if not any(row.what_category == what for row in review_rows):
        return {"status": "unavailable", "reason": f"no_review_rows_for_{what}"}

    metrics = evaluate_core_coverage(
        review_path,
        what,
        ids,
        plan_applied=False,
    )
    metrics.pop("plan_application", None)
    metrics["assessment_basis"] = basis
    if basis == "recorded_selection":
        missing_reason = "not_in_recorded_selection"
    else:
        missing_reason = "not_reported_as_used"
    metrics["missing_required_reasons"] = {
        unit_id: missing_reason for unit_id in metrics["missing_required_ids"]
    }
    return {"status": "evaluated", **metrics}


def _pair_labels(
    core_ids: list[str] | None,
    supporting_ids: list[str] | None,
    review_pairs: dict[tuple[str, str], str] | None,
) -> dict:
    if review_pairs is None:
        return {"status": "unavailable", "reason": "no_matching_supporting_review_csv"}
    if core_ids is None or supporting_ids is None:
        return {"status": "unavailable", "reason": "unit_ids_are_unknown"}
    pairs = []
    for core_id in core_ids:
        for supporting_id in supporting_ids:
            pairs.append({
                "core_unit_id": core_id,
                "supporting_unit_id": supporting_id,
                "label": review_pairs.get((core_id, supporting_id), "UNREVIEWED"),
            })
    counts = Counter(pair["label"] for pair in pairs)
    return {
        "status": "evaluated",
        "pairs": pairs,
        "label_counts": {label: counts.get(label, 0) for label in (
            "RELEVANT", "NOT_RELEVANT", "REVIEW_NEEDED", "PENDING", "UNREVIEWED",
        )},
        "interpretation": "Review labels describe candidate-pair relevance, not whether the generated text used the evidence correctly.",
    }


def _snapshot_gaps(ids: list[str] | None, units: list[dict] | None) -> list[str] | None:
    if ids is None or units is None:
        return None
    unit_ids = {unit["id"] for unit in units}
    return sorted(set(ids) - unit_ids)


def _record_evaluation(
    record: dict,
    core_reviews: dict[str, tuple[Path, list[CoreReviewRow]]],
    supporting_reviews: dict[str, dict[tuple[str, str], str]],
) -> dict:
    artwork_id = record["artwork"]["id"]
    core_review = core_reviews.get(artwork_id) if artwork_id else None
    core_path, core_rows = core_review if core_review else (None, None)
    pair_reviews = supporting_reviews.get(artwork_id) if artwork_id else None
    selection = record["selection"]
    generation = record["generation"]
    profile = record["profile"]

    selected_core = selection["selected_core_unit_ids"]
    selected_support = selection["selected_supporting_unit_ids"]
    used_core = generation["used_core_unit_ids"]
    used_support = generation["used_supporting_unit_ids"]
    return {
        "record_id": record["record_id"],
        "data_origin": record["data_origin"],
        "origin_verification": "Declared in input; not independently verified.",
        "provenance": record["provenance"],
        "quality_assessment_status": "not_semantically_assessed",
        "artwork_id": artwork_id,
        "profile": profile,
        "generation_status": generation["status"],
        "text_available": generation["text"] is not None,
        "model": generation["model"],
        "requested_model": generation["requested_model"],
        "evidence_insufficient": generation["evidence_insufficient"],
        "selection_strategy": selection["strategy"],
        "selected_core_unit_ids": selected_core,
        "selected_supporting_unit_ids": selected_support,
        "reported_used_core_unit_ids": used_core,
        "reported_used_supporting_unit_ids": used_support,
        "used_ids_not_in_selection": {
            "core": sorted(set(used_core or ()) - set(selected_core or ()))
            if used_core is not None and selected_core is not None else None,
            "supporting": sorted(set(used_support or ()) - set(selected_support or ()))
            if used_support is not None and selected_support is not None else None,
        },
        "snapshot_missing_selected_ids": {
            "core": _snapshot_gaps(selected_core, selection["core_units"]),
            "supporting": _snapshot_gaps(selected_support, selection["supporting_units"]),
        },
        "core_coverage": {
            "selected_core": _coverage_for_ids(
                core_path, core_rows, record, profile["what"], selected_core, "recorded_selection",
            ),
            "reported_used_core": _coverage_for_ids(
                core_path, core_rows, record, profile["what"], used_core, "reported_generation_usage",
            ),
        },
        "supporting_pair_review": {
            "selected_pairs": _pair_labels(selected_core, selected_support, pair_reviews),
            "reported_used_pairs": _pair_labels(used_core, used_support, pair_reviews),
        },
        "groundedness": {
            "status": "not_evaluated",
            "reason": "Requires sentence-level semantic review; ID declarations and text overlap do not prove factual support.",
        },
    }


def _surface_metrics(before_text: str, after_text: str) -> dict:
    before_normalized = " ".join(before_text.split())
    after_normalized = " ".join(after_text.split())
    before_tokens = set(re.findall(r"[^\W\d_]+", before_normalized.casefold()))
    after_tokens = set(re.findall(r"[^\W\d_]+", after_normalized.casefold()))
    union = before_tokens | after_tokens
    return {
        "exact_match_after_whitespace_normalization": before_normalized == after_normalized,
        "sequence_similarity": SequenceMatcher(
            None, before_normalized, after_normalized, autojunk=False,
        ).ratio(),
        "token_jaccard": len(before_tokens & after_tokens) / len(union) if union else 1.0,
        "before_character_count": len(before_text),
        "after_character_count": len(after_text),
        "interpretation": "Surface-form comparison only; not a semantic or quality judgment.",
    }


def compare_personalization_pairs(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for record in records:
        pair_id = record["comparison"]["pair_id"]
        if pair_id:
            groups[pair_id].append(record)

    results = []
    for pair_id, pair in sorted(groups.items()):
        item = {"comparison_id": pair_id, "status": "invalid_pair"}
        if len(pair) != 2 or {row["comparison"]["role"] for row in pair} != COMPARISON_ROLES:
            item["reason"] = "Each comparison_id must contain exactly one baseline and one variant record."
            results.append(item)
            continue
        before = next(row for row in pair if row["comparison"]["role"] == "baseline")
        after = next(row for row in pair if row["comparison"]["role"] == "variant")
        item.update({
            "baseline_record_id": before["record_id"],
            "variant_record_id": after["record_id"],
            "artwork_id": before["artwork"]["id"],
            "data_origin": before["data_origin"],
            "origin_verification": "Declared in input; not independently verified.",
        })
        if before["artwork"]["id"] is None or after["artwork"]["id"] is None:
            item["reason"] = "Cannot verify that both records refer to the same artwork."
            results.append(item)
            continue
        if before["artwork"]["id"] != after["artwork"]["id"]:
            item["reason"] = "Artwork IDs differ."
            results.append(item)
            continue
        if before["data_origin"] != after["data_origin"]:
            item["reason"] = "Pair mixes actual and mock records."
            results.append(item)
            continue
        before_profile = before["profile"]
        after_profile = after["profile"]
        if any(before_profile[key] is None or after_profile[key] is None for key in ("why", "what", "how")):
            item["reason"] = "Cannot identify a one-factor change while a profile value is unknown."
            results.append(item)
            continue
        changed = [
            key for key in ("why", "what", "how")
            if before_profile[key] != after_profile[key]
        ]
        declared_factors = {
            row["comparison"]["changed_factor"] for row in (before, after)
            if row["comparison"]["changed_factor"] is not None
        }
        if len(declared_factors) > 1 or (declared_factors and changed != [next(iter(declared_factors))]):
            item["reason"] = "Declared changed_factor does not match the profiles."
            results.append(item)
            continue
        if len(changed) != 1:
            item["reason"] = "A valid pair must change exactly one of WHY, WHAT, or HOW."
            results.append(item)
            continue
        item["changed_factor"] = changed[0]
        if (before["generation"]["status"] != "completed"
            or after["generation"]["status"] != "completed"
            or before["generation"]["text"] is None
            or after["generation"]["text"] is None):
            item["status"] = "not_compared"
            item["reason"] = "Both records need a completed generation with a saved text body."
            results.append(item)
            continue

        before_selection = before["selection"]
        after_selection = after["selection"]
        item["status"] = "surface_compared"
        item["surface_difference"] = _surface_metrics(
            before["generation"]["text"], after["generation"]["text"],
        )
        item["selection_changed"] = {
            "core": (
                set(before_selection["selected_core_unit_ids"])
                != set(after_selection["selected_core_unit_ids"])
                if before_selection["selected_core_unit_ids"] is not None
                and after_selection["selected_core_unit_ids"] is not None else None
            ),
            "supporting": (
                set(before_selection["selected_supporting_unit_ids"])
                != set(after_selection["selected_supporting_unit_ids"])
                if before_selection["selected_supporting_unit_ids"] is not None
                and after_selection["selected_supporting_unit_ids"] is not None else None
            ),
        }
        item["reported_usage_changed"] = {
            "core": (
                set(before["generation"]["used_core_unit_ids"])
                != set(after["generation"]["used_core_unit_ids"])
                if before["generation"]["used_core_unit_ids"] is not None
                and after["generation"]["used_core_unit_ids"] is not None else None
            ),
            "supporting": (
                set(before["generation"]["used_supporting_unit_ids"])
                != set(after["generation"]["used_supporting_unit_ids"])
                if before["generation"]["used_supporting_unit_ids"] is not None
                and after["generation"]["used_supporting_unit_ids"] is not None else None
            ),
        }
        item["assessment_scope"] = (
            "mock_validation_only" if before["data_origin"] == "mock"
            else "actual_text_surface_difference_only"
        )
        item["quality_assessment_status"] = "not_semantically_assessed"
        results.append(item)
    return results


def evaluate_saved_records(
    records: list[dict],
    core_review_paths: list[Path] | None = None,
    supporting_review_paths: list[Path] | None = None,
) -> dict:
    core_reviews = _load_core_reviews(core_review_paths or [])
    supporting_reviews = {}
    for path in supporting_review_paths or []:
        artwork_id, pairs = _load_supporting_review(path)
        if artwork_id in supporting_reviews:
            raise ValueError(f"Multiple Supporting review CSVs supplied for artwork {artwork_id}.")
        supporting_reviews[artwork_id] = pairs

    origins = Counter(record["data_origin"] for record in records)
    evaluations = [
        _record_evaluation(record, core_reviews, supporting_reviews)
        for record in records
    ]
    return {
        "report_schema_version": SCHEMA_VERSION,
        "dataset": {
            "record_count": len(records),
            "actual_record_count": origins.get("actual", 0),
            "mock_record_count": origins.get("mock", 0),
            "origin_verification": "The data_origin field is declared by the input record and is not independently verified.",
            "classification": (
                "mock_only" if origins.get("mock") and not origins.get("actual")
                else "actual_only" if origins.get("actual") and not origins.get("mock")
                else "mixed" if origins.get("actual") and origins.get("mock")
                else "empty"
            ),
        },
        "offline_capabilities": [
            "REQUIRED Core coverage for recorded selected IDs and reported-used IDs, when review CSVs and IDs are known.",
            "Selected Core/Supporting pair labels from human review CSVs, without inferring text-level usage.",
            "Recorded-vs-used ID consistency and selected Unit snapshot completeness.",
            "One-factor profile validation and surface-level text differences for paired records.",
        ],
        "not_evaluated": {
            "groundedness": "Not determined offline; word overlap, selected IDs, and model-reported IDs are not factual verification.",
            "semantic_personalization_quality": "Text difference metrics do not determine whether the change is intentional or appropriate.",
            "gemini_sentence_audit": "Not run; the existing sentence audit calls Gemini.",
        },
        "records": evaluations,
        "personalization_comparisons": compare_personalization_pairs(records),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_jsonl", type=Path, help="Saved docent records in docent-evaluation/v1 format")
    parser.add_argument("output_json", type=Path, help="New offline evaluation report; existing files are not overwritten")
    parser.add_argument(
        "--core-review", type=Path, action="append", default=[],
        help="Core Coverage review CSV; repeat once per artwork",
    )
    parser.add_argument(
        "--supporting-review", type=Path, action="append", default=[],
        help="Core/Supporting relevance review CSV; repeat once per artwork",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        input_path = args.input_jsonl.resolve()
        output_path = args.output_json.resolve()
        review_paths = [path.resolve() for path in args.core_review + args.supporting_review]
        if output_path == input_path or output_path in review_paths:
            raise ValueError("Output path must differ from all input paths.")
        records = load_saved_jsonl(input_path)
        report = evaluate_saved_records(records, args.core_review, args.supporting_review)
        write_report(output_path, report)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(
        f"Evaluated {report['dataset']['record_count']} saved records "
        f"({report['dataset']['classification']}); no model/API calls made."
    )


if __name__ == "__main__":
    main()
