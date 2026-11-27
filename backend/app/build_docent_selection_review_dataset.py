"""Build a local review CSV; the improved selector is an offline simulation, not live service logic."""

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from .docent import KOREAN_ENDING, evidence_terms
from .docent_csv_input import load_approved_what_csv
from .gemini_units import normalize
from .schemas import Category


WHAT_CHOICES = get_args(Category)
LEGACY_GENERIC_TERMS = {
    "작품", "작가", "그림", "화면", "표현", "구성", "사용", "제작", "대상", "단서",
    "이러한", "그리고", "때문", "해당", "통해", "대한", "the", "and", "with", "from",
}
ENGLISH_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "as", "at", "by", "for", "from", "in",
    "into", "of", "on", "onto", "to", "with", "is", "are", "was", "were", "be",
    "been", "being", "do", "does", "did", "has", "have", "had", "it", "its", "this",
    "that", "these", "those", "there", "where", "when", "while", "who", "which",
    "would", "could", "should", "their", "they", "them", "we", "you", "your", "our",
    "one", "each",
}
CSV_COLUMNS = [
    "artwork_id",
    "artwork_name",
    "what_category",
    "core_unit_id",
    "core_category",
    "core_content",
    "core_selected_legacy",
    "core_selected_improved",
    "supporting_unit_id",
    "supporting_category",
    "supporting_content",
    "candidate_is_duplicate",
    "legacy_pair_score",
    "legacy_pair_overlap_terms",
    "legacy_core_rank",
    "improved_pair_score",
    "improved_pair_overlap_terms",
    "improved_core_rank",
    "legacy_global_score",
    "legacy_global_rank",
    "legacy_global_selected",
    "improved_global_score",
    "improved_global_rank",
    "improved_global_selected",
    "relevance_label",
    "relation_type",
    "review_reason",
    "review_status",
]


@dataclass(frozen=True)
class ReviewUnit:
    id: str
    content: str
    category: str


def legacy_evidence_terms(content):
    words = re.findall(r"[^\W\d_]+", content.casefold())
    return {
        stem for word in words if len(stem := KOREAN_ENDING.sub("", word)) >= 2
    } - LEGACY_GENERIC_TERMS


def improved_evidence_terms(content):
    return evidence_terms(content) - ENGLISH_FUNCTION_WORDS


def proper_name_terms(content):
    words = list(re.finditer(r"[^\W\d_]+(?:['’][^\W\d_]+)?", content))
    names = set()
    for index, match in enumerate(words):
        word = match.group()
        prefix = content[:match.start()]
        sentence_start = not prefix.strip() or bool(re.search(r"[.!?]\s*$", prefix))
        next_is_capitalized = (
            index + 1 < len(words)
            and words[index + 1].group()[0].isupper()
            and not re.search(r"[.!?]", content[match.end():words[index + 1].start()])
        )
        if word[0].isupper() and (not sentence_start or next_is_capitalized):
            names.add(re.sub(r"['’]s$", "", word, flags=re.IGNORECASE).casefold())
    return names


def _unique_units(units, category):
    unique = {}
    duplicate_ids = set()
    for unit in sorted(units, key=lambda item: item.category != category):
        key = normalize(unit.content).casefold()
        if key in unique:
            duplicate_ids.add(unit.id)
        else:
            unique[key] = unit
    return list(unique.values()), duplicate_ids


def _improved_select_units(units, category, limit, artwork):
    unique, _ = _unique_units(units, category)
    matching = [unit for unit in unique if unit.category == category]
    other = [unit for unit in unique if unit.category != category]
    if not matching:
        return [], other[:min(2, limit)]

    core = matching[:limit]
    identifying_terms = improved_evidence_terms(
        f"{artwork.get('name', '')} {artwork.get('artist', '')}"
    )
    terms = {
        unit.id: improved_evidence_terms(unit.content)
        - identifying_terms
        - proper_name_terms(unit.content)
        for unit in unique
    }
    ranked = []
    for unit in other:
        score = max(len(terms[unit.id] & terms[core_unit.id]) for core_unit in core)
        if score:
            ranked.append((score, unit))
    ranked.sort(key=lambda pair: pair[0], reverse=True)

    if len(core) == limit and limit > 1 and any(
        terms[unit.id] & terms[core_unit.id]
        for _, unit in ranked for core_unit in core[:-1]
    ):
        core.pop()

    supporting = []
    for _, unit in ranked:
        if len(supporting) == min(2, limit - len(core)):
            break
        if any(terms[unit.id] & terms[core_unit.id] for core_unit in core):
            supporting.append(unit)
    return core, supporting


def _legacy_select(units, category, limit, terms_by_id):
    unique, duplicate_ids = _unique_units(units, category)
    matching = [unit for unit in unique if unit.category == category]
    other = [unit for unit in unique if unit.category != category]
    if not matching:
        return [], other[:min(2, limit)], other, duplicate_ids

    core = matching[:limit]
    ranked = []
    for unit in other:
        score = max(len(terms_by_id[unit.id] & terms_by_id[core_unit.id]) for core_unit in core)
        if score:
            ranked.append((score, unit))
    ranked.sort(key=lambda pair: pair[0], reverse=True)

    if len(core) == limit and limit > 1 and any(
        terms_by_id[unit.id] & terms_by_id[core_unit.id]
        for _, unit in ranked for core_unit in core[:-1]
    ):
        core.pop()

    supporting = []
    for _, unit in ranked:
        if len(supporting) == min(2, limit - len(core)):
            break
        if any(terms_by_id[unit.id] & terms_by_id[core_unit.id] for core_unit in core):
            supporting.append(unit)
    return core, supporting, other, duplicate_ids


def _global_scores(core, candidates, terms_by_id):
    return {
        candidate.id: max(
            (len(terms_by_id[candidate.id] & terms_by_id[core_unit.id]) for core_unit in core),
            default=0,
        )
        for candidate in candidates
    }


def _positive_ranks(candidates, scores):
    eligible = [candidate for candidate in candidates if scores.get(candidate.id, 0) > 0]
    ranked = sorted(eligible, key=lambda candidate: scores[candidate.id], reverse=True)
    return {candidate.id: rank for rank, candidate in enumerate(ranked, start=1)}


def build_review_rows(artwork, units, unit_limit=6):
    if not 1 <= unit_limit <= 6:
        raise ValueError("unit_limit must be between 1 and 6.")

    artwork_terms_legacy = legacy_evidence_terms(
        f"{artwork.get('name', '')} {artwork.get('artist', '')}"
    )
    artwork_terms_improved = improved_evidence_terms(
        f"{artwork.get('name', '')} {artwork.get('artist', '')}"
    )
    legacy_terms = {
        unit.id: legacy_evidence_terms(unit.content) - artwork_terms_legacy
        for unit in units
    }
    improved_terms = {
        unit.id: improved_evidence_terms(unit.content)
        - artwork_terms_improved
        - proper_name_terms(unit.content)
        for unit in units
    }

    rows = []
    for category in WHAT_CHOICES:
        cores = [unit for unit in units if unit.category == category]
        candidates = [unit for unit in units if unit.category != category]
        if not cores:
            continue

        legacy_core, legacy_support, legacy_candidates, legacy_duplicates = _legacy_select(
            units, category, unit_limit, legacy_terms,
        )
        improved_core, improved_support = _improved_select_units(
            units, category, unit_limit,
            artwork,
        )
        improved_unique, improved_duplicates = _unique_units(units, category)
        improved_candidates = [unit for unit in improved_unique if unit.category != category]

        legacy_global_scores = _global_scores(legacy_core, legacy_candidates, legacy_terms)
        improved_global_scores = _global_scores(
            improved_core, improved_candidates, improved_terms,
        )
        legacy_global_ranks = _positive_ranks(legacy_candidates, legacy_global_scores)
        improved_global_ranks = _positive_ranks(improved_candidates, improved_global_scores)
        legacy_selected_ids = {unit.id for unit in legacy_support}
        improved_selected_ids = {unit.id for unit in improved_support}
        legacy_core_ids = {unit.id for unit in legacy_core}
        improved_core_ids = {unit.id for unit in improved_core}

        legacy_pair_scores = {
            (core.id, candidate.id): len(legacy_terms[core.id] & legacy_terms[candidate.id])
            for core in cores for candidate in candidates
        }
        improved_pair_scores = {
            (core.id, candidate.id): len(improved_terms[core.id] & improved_terms[candidate.id])
            for core in cores for candidate in candidates
        }
        legacy_pair_ranks = {}
        improved_pair_ranks = {}
        for core in cores:
            legacy_order = sorted(
                candidates,
                key=lambda candidate: legacy_pair_scores[core.id, candidate.id],
                reverse=True,
            )
            improved_order = sorted(
                candidates,
                key=lambda candidate: improved_pair_scores[core.id, candidate.id],
                reverse=True,
            )
            legacy_pair_ranks.update(
                {(core.id, candidate.id): rank for rank, candidate in enumerate(legacy_order, start=1)}
            )
            improved_pair_ranks.update(
                {(core.id, candidate.id): rank for rank, candidate in enumerate(improved_order, start=1)}
            )

        for core in cores:
            for candidate in candidates:
                legacy_overlap = sorted(legacy_terms[core.id] & legacy_terms[candidate.id])
                improved_overlap = sorted(improved_terms[core.id] & improved_terms[candidate.id])
                rows.append({
                    "artwork_id": artwork["id"],
                    "artwork_name": artwork["name"],
                    "what_category": category,
                    "core_unit_id": core.id,
                    "core_category": core.category,
                    "core_content": core.content,
                    "core_selected_legacy": str(core.id in legacy_core_ids).lower(),
                    "core_selected_improved": str(core.id in improved_core_ids).lower(),
                    "supporting_unit_id": candidate.id,
                    "supporting_category": candidate.category,
                    "supporting_content": candidate.content,
                    "candidate_is_duplicate": str(
                        candidate.id in legacy_duplicates or candidate.id in improved_duplicates
                    ).lower(),
                    "legacy_pair_score": legacy_pair_scores[core.id, candidate.id],
                    "legacy_pair_overlap_terms": "|".join(legacy_overlap),
                    "legacy_core_rank": legacy_pair_ranks[core.id, candidate.id],
                    "improved_pair_score": improved_pair_scores[core.id, candidate.id],
                    "improved_pair_overlap_terms": "|".join(improved_overlap),
                    "improved_core_rank": improved_pair_ranks[core.id, candidate.id],
                    "legacy_global_score": legacy_global_scores.get(candidate.id, 0),
                    "legacy_global_rank": legacy_global_ranks.get(candidate.id, ""),
                    "legacy_global_selected": str(candidate.id in legacy_selected_ids).lower(),
                    "improved_global_score": improved_global_scores.get(candidate.id, 0),
                    "improved_global_rank": improved_global_ranks.get(candidate.id, ""),
                    "improved_global_selected": str(candidate.id in improved_selected_ids).lower(),
                    "relevance_label": "PENDING",
                    "relation_type": "PENDING",
                    "review_reason": "PENDING",
                    "review_status": "PENDING",
                })
    return rows


def write_review_csv(path, rows):
    if not path.parent.exists():
        raise ValueError(f"Output directory does not exist: {path.parent}")
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def positive_unit_limit(value):
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("unit limit must be an integer from 1 to 6.") from error
    if not 1 <= limit <= 6:
        raise argparse.ArgumentTypeError("unit limit must be an integer from 1 to 6.")
    return limit


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Approved WHAT 4-class CSV")
    parser.add_argument("--artwork-id", required=True, help="Exact source artwork_id")
    parser.add_argument(
        "--output", type=Path, required=True,
        help="New review CSV path; existing files are not overwritten",
    )
    parser.add_argument("--unit-limit", type=positive_unit_limit, default=6)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        record = load_approved_what_csv(args.input, args.artwork_id)
        units = [ReviewUnit(**unit) for unit in record["units"]]
        rows = build_review_rows(record["artwork"], units, args.unit_limit)
        write_review_csv(args.output, rows)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    counts = Counter(unit.category for unit in units)
    print(json.dumps({
        "artwork_id": args.artwork_id,
        "artwork_name": record["artwork"]["name"],
        "unit_count": len(units),
        "units_by_category": {category: counts.get(category, 0) for category in WHAT_CHOICES},
        "what_categories_evaluated": [category for category in WHAT_CHOICES if counts[category]],
        "pair_count": len(rows),
        "pending_rows": sum(row["review_status"] == "PENDING" for row in rows),
        "output": str(args.output.resolve()),
    }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
