import csv
from pathlib import Path
from typing import get_args

from .schemas import Category


def load_approved_what_csv(path: Path, artwork_id: str) -> dict:
    required = {
        "artwork_id", "artwork_title", "unit_id", "text",
        "gold_category", "human_approval", "new_action",
    }
    rows = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open(encoding=encoding, newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or not required <= set(reader.fieldnames):
                    missing = sorted(required - set(reader.fieldnames or ()))
                    raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
        except OSError as error:
            raise ValueError(f"Cannot read CSV input: {type(error).__name__}") from None
    if rows is None:
        raise ValueError("CSV encoding is not supported; save it as UTF-8 or CP949.")

    matching = [row for row in rows if (row.get("artwork_id") or "").strip() == artwork_id]
    if not matching:
        raise ValueError(f"No rows found for artwork_id={artwork_id}.")

    approved_keep = [
        row for row in matching
        if (row.get("human_approval") or "").strip().upper() == "APPROVED"
        and (row.get("new_action") or "").strip().upper() == "KEEP"
    ]
    if not approved_keep:
        raise ValueError("No rows are both human_approval=APPROVED and new_action=KEEP.")

    titles = {(row.get("artwork_title") or "").strip() for row in matching}
    if len(titles) != 1 or not next(iter(titles)):
        raise ValueError("Selected artwork rows must contain one consistent non-empty artwork_title.")

    valid_categories = get_args(Category)
    units = []
    seen_ids = set()
    for index, row in enumerate(approved_keep, start=2):
        unit_id = (row.get("unit_id") or "").strip()
        content = (row.get("text") or "").strip()
        category = (row.get("gold_category") or "").strip().upper()
        if not unit_id or not content:
            raise ValueError(f"Approved KEEP row {index} is missing unit_id or text.")
        if unit_id in seen_ids:
            raise ValueError(f"Duplicate unit_id in selected artwork: {unit_id}.")
        if category not in valid_categories:
            raise ValueError(f"Approved KEEP row {index} has an invalid gold_category.")
        seen_ids.add(unit_id)
        units.append({"id": unit_id, "content": content, "category": category})

    approval_basis_values = {
        (row.get("approval_basis") or "").strip()
        for row in approved_keep if "approval_basis" in row
    }
    source_metadata = {
        "source_csv": path.name,
        "artwork_id_column": "artwork_id",
        "unit_id_column": "unit_id",
        "category_column": "gold_category",
        "approval_filter": "human_approval=APPROVED and new_action=KEEP",
        "publication_status": "not present in source; not asserted",
        "matching_rows": str(len(matching)),
        "included_rows": str(len(units)),
        "excluded_rows": str(len(matching) - len(units)),
    }
    if len(approval_basis_values) == 1 and next(iter(approval_basis_values)):
        source_metadata["approval_basis"] = next(iter(approval_basis_values))

    return {
        "artwork": {"id": artwork_id, "name": next(iter(titles))},
        "units": units,
        "source_metadata": source_metadata,
    }
