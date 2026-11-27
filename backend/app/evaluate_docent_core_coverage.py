"""Offline evaluation of reviewed Core requirements against EvidencePlan output."""

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .docent import EvidencePlan, UnitSelection, apply_evidence_plan
from .schemas import Category


REVIEW_COLUMNS = {
    "artwork_id",
    "artwork_name",
    "what_category",
    "core_unit_id",
    "core_content",
    "essential_label",
    "semantic_aspect",
    "redundancy_group",
    "review_reason",
    "review_status",
}
ESSENTIAL_LABELS = {
    "REQUIRED",
    "OPTIONAL",
    "REVIEW_NEEDED",
    "EXCLUDE",
    "PENDING",
}


class Candidate(Protocol):
    id: Any
    category: str


@dataclass(frozen=True)
class CoreReviewRow:
    artwork_id: str
    artwork_name: str
    what_category: str
    core_unit_id: str
    core_content: str
    essential_label: str
    semantic_aspect: str
    redundancy_group: str
    review_reason: str
    review_status: str


@dataclass(frozen=True)
class PlanCoverageEvaluation:
    plan_applied: bool
    selection: UnitSelection
    metrics: dict[str, Any]


def load_core_coverage_review(path: Path) -> list[CoreReviewRow]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not REVIEW_COLUMNS <= set(reader.fieldnames):
            missing = sorted(REVIEW_COLUMNS - set(reader.fieldnames or ()))
            raise ValueError(f"Core coverage CSV is missing columns: {', '.join(missing)}")
        raw_rows = list(reader)

    if not raw_rows:
        raise ValueError(f"Core coverage CSV has no review rows: {path}")

    rows = []
    seen = set()
    artwork_ids = set()
    artwork_names = set()
    for line_number, raw in enumerate(raw_rows, start=2):
        row = CoreReviewRow(
            artwork_id=(raw["artwork_id"] or "").strip(),
            artwork_name=(raw["artwork_name"] or "").strip(),
            what_category=(raw["what_category"] or "").strip().upper(),
            core_unit_id=(raw["core_unit_id"] or "").strip(),
            core_content=(raw["core_content"] or "").strip(),
            essential_label=(raw["essential_label"] or "").strip().upper(),
            semantic_aspect=(raw["semantic_aspect"] or "").strip(),
            redundancy_group=(raw["redundancy_group"] or "").strip(),
            review_reason=(raw["review_reason"] or "").strip(),
            review_status=(raw["review_status"] or "").strip(),
        )
        if not all((row.artwork_id, row.artwork_name, row.core_unit_id, row.core_content)):
            raise ValueError(f"Core coverage CSV has an empty identity or content at line {line_number}.")
        if row.what_category not in Category.__args__:
            raise ValueError(f"Invalid WHAT category at line {line_number}: {row.what_category}")
        if row.essential_label not in ESSENTIAL_LABELS:
            raise ValueError(f"Invalid essential_label at line {line_number}: {row.essential_label}")
        key = (row.artwork_id, row.what_category, row.core_unit_id)
        if key in seen:
            raise ValueError(f"Duplicate Core review row at line {line_number}: {row.core_unit_id}")
        seen.add(key)
        artwork_ids.add(row.artwork_id)
        artwork_names.add(row.artwork_name)
        rows.append(row)

    if len(artwork_ids) != 1 or len(artwork_names) != 1:
        raise ValueError("Core coverage CSV must contain exactly one artwork ID and name.")
    return rows


def evaluate_core_coverage(
    review_csv: Path,
    what_category: str,
    selected_core_ids: Iterable[str],
    *,
    plan_core_refs: Iterable[int] = (),
    candidate_refs: Mapping[int, Candidate] | None = None,
    candidate_review_ids: Mapping[int, str] | None = None,
    unit_limit: int | None = None,
    selected_supporting_count: int = 0,
    plan_applied: bool = True,
    fallback_excluded: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    category = what_category.upper()
    if category not in Category.__args__:
        raise ValueError(f"Invalid WHAT category: {what_category}")
    if unit_limit is not None and not 1 <= unit_limit <= 6:
        raise ValueError("unit_limit must be between 1 and 6.")

    rows = [
        row for row in load_core_coverage_review(review_csv)
        if row.what_category == category
    ]
    if not rows:
        raise ValueError(f"No reviewed Core candidates for WHAT={category}.")

    selected = [str(unit_id) for unit_id in selected_core_ids]
    selected_set = set(selected)
    selected_counts = Counter(selected)
    by_label = {
        label: {row.core_unit_id for row in rows if row.essential_label == label}
        for label in ESSENTIAL_LABELS
    }
    required_ids = by_label["REQUIRED"]
    missing_required = required_ids - selected_set
    optional_ids = by_label["OPTIONAL"]
    review_needed_ids = by_label["REVIEW_NEEDED"]
    candidate_ids = {row.core_unit_id for row in rows}

    refs = candidate_refs or {}
    review_id_by_ref = candidate_review_ids or {}
    internal_to_review_id = {}
    valid_plan_refs = []
    valid_plan_ids = []
    invalid_plan_refs = []
    invalid_plan_unit_ids = set()
    raw_plan_refs = list(plan_core_refs)
    ref_counts = Counter(raw_plan_refs)
    duplicate_plan_refs = [
        {
            "ref": ref,
            "core_unit_id": review_id_by_ref.get(ref, str(getattr(refs.get(ref), "id", ""))) or None,
        }
        for ref, count in ref_counts.items() if count > 1
    ]

    for ref, candidate in refs.items():
        internal_to_review_id[str(candidate.id)] = review_id_by_ref.get(ref, str(candidate.id))

    seen_plan_refs = set()
    seen_plan_ids = set()
    for ref in raw_plan_refs:
        if ref not in refs:
            invalid_plan_refs.append({"ref": ref, "reason": "unknown_reference"})
            continue
        candidate = refs[ref]
        review_id = review_id_by_ref.get(ref, str(candidate.id))
        if candidate.category != category:
            invalid_plan_refs.append({
                "ref": ref,
                "core_unit_id": review_id,
                "reason": "category_mismatch",
            })
            invalid_plan_unit_ids.add(review_id)
            continue
        if ref in seen_plan_refs:
            continue
        seen_plan_refs.add(ref)
        valid_plan_refs.append(ref)
        if review_id not in seen_plan_ids:
            seen_plan_ids.add(review_id)
            valid_plan_ids.append(review_id)

    plan_id_set = set(valid_plan_ids)
    candidate_core_ids = {
        review_id_by_ref.get(ref, str(candidate.id))
        for ref, candidate in refs.items()
        if candidate.category == category
    }
    missing_from_candidates = required_ids - candidate_core_ids
    unit_limit_excluded = set()
    if plan_applied and unit_limit is not None:
        core_budget = max(0, unit_limit - selected_supporting_count)
        if len(valid_plan_refs) > core_budget:
            unit_limit_excluded = plan_id_set - selected_set

    fallback_excluded_ids = {
        internal_to_review_id.get(str(unit_id), str(unit_id))
        for unit_id, reason in (fallback_excluded or {}).items()
        if reason == "selection_limit"
    }
    missing_reasons = {}
    for unit_id in sorted(missing_required):
        if unit_id in invalid_plan_unit_ids:
            reason = "invalid_category_reference"
        elif unit_id in missing_from_candidates:
            reason = "review_core_not_in_plan_candidates"
        elif unit_id in unit_limit_excluded:
            reason = "unit_limit"
        elif plan_applied and unit_id not in plan_id_set:
            reason = "omitted_by_plan"
        elif plan_applied:
            reason = "not_retained_by_applied_plan"
        elif unit_id in fallback_excluded_ids:
            reason = "fallback_unit_limit"
        else:
            reason = "not_selected_by_fallback"
        missing_reasons[unit_id] = reason

    selected_redundancy_groups: dict[str, list[str]] = {}
    for row in rows:
        if row.core_unit_id in selected_set and row.redundancy_group:
            selected_redundancy_groups.setdefault(row.redundancy_group, []).append(row.core_unit_id)

    return {
        "artwork_id": rows[0].artwork_id,
        "artwork_name": rows[0].artwork_name,
        "what_category": category,
        "plan_application": "semantic" if plan_applied else "local_fallback",
        "candidate_count": len(rows),
        "selected_core_ids": sorted(selected_set),
        "duplicate_selected_core_ids": sorted(
            unit_id for unit_id, count in selected_counts.items() if count > 1
        ),
        "required_core_ids": sorted(required_ids),
        "required_coverage": {
            "covered": len(required_ids & selected_set),
            "required": len(required_ids),
            "ratio": len(required_ids & selected_set) / len(required_ids) if required_ids else None,
        },
        "missing_required_ids": sorted(missing_required),
        "missing_required_reasons": missing_reasons,
        "optional_core_ids": sorted(optional_ids),
        "optional_selected_ids": sorted(optional_ids & selected_set),
        "optional_missing_ids": sorted(optional_ids - selected_set),
        "review_needed_core_ids": sorted(review_needed_ids),
        "review_needed_selected_ids": sorted(review_needed_ids & selected_set),
        "review_needed_missing_ids": sorted(review_needed_ids - selected_set),
        "exclude_selected_ids": sorted(by_label["EXCLUDE"] & selected_set),
        "pending_label_ids": sorted(by_label["PENDING"]),
        "unexpected_selected_core_ids": sorted(selected_set - candidate_ids),
        "review_required_ids_missing_from_plan_candidates": sorted(missing_from_candidates),
        "duplicate_plan_refs": duplicate_plan_refs,
        "invalid_plan_refs": invalid_plan_refs,
        "valid_planned_core_ids": valid_plan_ids,
        "unit_limit_excluded_core_ids": sorted(unit_limit_excluded),
        "selected_redundancy_groups": selected_redundancy_groups,
    }


def evaluate_plan_application(
    review_csv: Path,
    what_category: str,
    candidates: Mapping[int, Candidate],
    unit_limit: int,
    fallback: UnitSelection,
    plan: EvidencePlan,
    *,
    candidate_review_ids: Mapping[int, str] | None = None,
) -> PlanCoverageEvaluation:
    applied = apply_evidence_plan(
        candidates, what_category, unit_limit, fallback, plan,
    )
    selection = applied if applied is not None else fallback
    review_id_by_ref = candidate_review_ids or {}
    internal_to_review_id = {
        str(candidate.id): review_id_by_ref.get(ref, str(candidate.id))
        for ref, candidate in candidates.items()
    }
    selected_ids = [
        internal_to_review_id.get(str(unit.id), str(unit.id))
        for unit in selection.core
    ]
    fallback_excluded = fallback.excluded if applied is None else {}
    metrics = evaluate_core_coverage(
        review_csv,
        what_category,
        selected_ids,
        plan_core_refs=plan.core_refs,
        candidate_refs=candidates,
        candidate_review_ids=review_id_by_ref,
        unit_limit=unit_limit,
        selected_supporting_count=len(applied.supporting) if applied is not None else 0,
        plan_applied=applied is not None,
        fallback_excluded=fallback_excluded,
    )
    return PlanCoverageEvaluation(
        plan_applied=applied is not None,
        selection=selection,
        metrics=metrics,
    )
