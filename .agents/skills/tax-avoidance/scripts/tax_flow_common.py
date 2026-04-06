from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WIKIPEDIA_AVOIDANCE = "https://en.wikipedia.org/wiki/Tax_avoidance"
WIKIPEDIA_EVASION = "https://en.wikipedia.org/wiki/Tax_evasion"

RULE_SOURCES: dict[str, dict[str, str]] = {
    "wages": {"title": "IRS Publication 17", "url": "https://www.irs.gov/publications/p17"},
    "federal_withholding": {"title": "IRS Publication 505", "url": "https://www.irs.gov/publications/p505"},
    "taxable_interest": {"title": "IRS Publication 17", "url": "https://www.irs.gov/publications/p17"},
    "ordinary_dividends": {"title": "IRS Publication 17", "url": "https://www.irs.gov/publications/p17"},
    "capital_gains": {"title": "IRS Publication 17", "url": "https://www.irs.gov/publications/p17"},
    "social_security_benefits": {"title": "IRS Publication 17", "url": "https://www.irs.gov/publications/p17"},
    "ira_contribution_deduction": {
        "title": "IRS Publication 590-A",
        "url": "https://www.irs.gov/publications/p590a",
    },
    "hsa_deduction": {
        "title": "IRS Publication 969",
        "url": "https://www.irs.gov/forms-pubs/about-publication-969",
    },
    "student_loan_interest_deduction": {
        "title": "IRS Publication 970",
        "url": "https://www.irs.gov/publications/p970",
    },
    "mortgage_interest": {
        "title": "IRS Publication 936",
        "url": "https://www.irs.gov/publications/p936",
    },
    "charitable_cash": {
        "title": "IRS Publication 526",
        "url": "https://www.irs.gov/publications/p526",
    },
    "education_credit": {
        "title": "IRS Publication 970",
        "url": "https://www.irs.gov/publications/p970",
    },
    "clean_vehicle_credit": {
        "title": "IRS Clean vehicle and energy credits",
        "url": "https://www.irs.gov/credits-deductions/clean-vehicle-and-energy-credits",
    },
    "clean_energy_credit": {
        "title": "IRS Clean vehicle and energy credits",
        "url": "https://www.irs.gov/credits-deductions/clean-vehicle-and-energy-credits",
    },
    "nonemployee_compensation": {
        "title": "IRS Publication 334",
        "url": "https://www.irs.gov/publications/p334",
    },
    "business_expenses": {
        "title": "IRS Publication 334",
        "url": "https://www.irs.gov/publications/p334",
    },
    "schedule_c": {
        "title": "About Schedule C (Form 1040)",
        "url": "https://www.irs.gov/forms-pubs/about-schedule-c-form-1040",
    },
    "schedule_se": {
        "title": "Instructions for Schedule SE (2025)",
        "url": "https://www.irs.gov/pub/irs-prior/i1040sse--2025.pdf",
    },
}

STATE_SUPPORT: dict[str, dict[str, str]] = {
    "CA": {
        "name": "California",
        "status": "planned",
        "resident_form": "Form 540",
        "nonresident_form": "Form 540NR",
        "source_url": "https://www.ftb.ca.gov/file/personal/do-you-need-to-file.html",
    },
    "NY": {
        "name": "New York",
        "status": "planned",
        "resident_form": "Form IT-201",
        "nonresident_form": "Form IT-203",
        "source_url": "https://www.tax.ny.gov/pit/file/residents.htm",
    },
}

ILLEGAL_PATTERNS = (
    "hide income",
    "skip reporting",
    "offshore",
    "shell company",
    "conceal ownership",
    "falsify deduction",
    "fake deduction",
    "tax evasion",
)

UNSUPPORTED_DOC_TYPES = {
    "1099-MISC": "Business-style miscellaneous income outside plain 1099-NEC contractor work is still out of scope for v1.",
    "Schedule E": "Rental income is out of scope for v1.",
    "K-1": "K-1 income is out of scope for v1.",
    "RSU Statement": "Equity compensation is out of scope for v1.",
    "Option Exercise": "Equity compensation is out of scope for v1.",
    "QSBS": "QSBS is out of scope for v1.",
}

SUPPORTED_STATUSES = {"single", "married_filing_jointly"}
SOCIAL_SECURITY_WAGE_BASE_BY_YEAR = {
    2025: 176_100.0,
}
SELF_EMPLOYMENT_NET_EARNINGS_FACTOR = 0.9235
SELF_EMPLOYMENT_SOCIAL_SECURITY_RATE = 0.124
SELF_EMPLOYMENT_MEDICARE_RATE = 0.029
SELF_EMPLOYMENT_FILING_THRESHOLD = 400.0
ADDITIONAL_MEDICARE_THRESHOLDS = {
    "single": 200_000.0,
    "married_filing_jointly": 250_000.0,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def aggregate_numeric(
    documents: list[dict[str, Any]],
    doc_types: set[str],
    field_name: str,
) -> tuple[float, list[dict[str, Any]]]:
    def source_rank(document: dict[str, Any]) -> tuple[int, int]:
        content_status = document.get("content_status", "")
        status_score = {
            "available": 4,
            "metadata_only": 3,
            "unreadable_encrypted_attachment": 2,
            "portal_notice_only": 1,
        }.get(content_status, 0)
        value_score = 1 if safe_float(document.get("fields", {}).get(field_name)) != 0.0 else 0
        return (value_score, status_score)

    grouped_documents: list[dict[str, Any]] = []
    dedupe_groups: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        if document.get("doc_type") not in doc_types:
            continue
        dedupe_key = document.get("dedupe_key")
        if dedupe_key:
            dedupe_groups.setdefault(dedupe_key, []).append(document)
        else:
            grouped_documents.append(document)

    for group in dedupe_groups.values():
        grouped_documents.append(max(group, key=source_rank))

    total = 0.0
    sources: list[dict[str, Any]] = []
    for document in grouped_documents:
        dedupe_key = document.get("dedupe_key")
        value = safe_float(document.get("fields", {}).get(field_name))
        if value == 0.0:
            continue
        total += value
        sources.append(
            {
                "doc_id": document.get("id"),
                "doc_type": document.get("doc_type"),
                "source_type": document.get("source_type"),
                "source_ref": document.get("source_ref"),
                "dedupe_key": dedupe_key,
                "field": field_name,
                "value": value,
            }
        )
    return total, sources


def answer_fact(
    answers: dict[str, Any],
    key: str,
    fallback: float = 0.0,
) -> tuple[float, list[dict[str, Any]]]:
    if key not in answers:
        return fallback, []
    value = safe_float(answers.get(key))
    if value == 0.0:
        return value, []
    return value, [{"source_type": "user_answer", "source_ref": f"answer:{key}", "field": key, "value": value}]


def detect_illegal_request(user_request: str) -> list[str]:
    lowered = user_request.lower()
    return [pattern for pattern in ILLEGAL_PATTERNS if pattern in lowered]


def detect_unsupported(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    filing_status = payload.get("filing_status", "")
    if filing_status and filing_status not in SUPPORTED_STATUSES:
        reasons.append(f"Unsupported filing status for v1: {filing_status}.")
    for document in payload.get("documents", []):
        doc_type = document.get("doc_type")
        if doc_type in UNSUPPORTED_DOC_TYPES:
            reasons.append(UNSUPPORTED_DOC_TYPES[doc_type])
    answers = payload.get("answers", {})
    if answers.get("has_multistate"):
        reasons.append("Multistate filing is out of scope for v1.")
    if answers.get("has_international"):
        reasons.append("International filing is out of scope for v1.")
    if answers.get("has_complex_equity"):
        reasons.append("Complex equity compensation is out of scope for v1.")
    return list(dict.fromkeys(reasons))


def connector_notes(connectors: dict[str, bool], documents: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    gmail = bool(connectors.get("gmail"))
    drive = bool(connectors.get("google_drive"))
    if gmail and drive:
        notes.append("Gmail and Google Drive are both connected.")
    elif gmail:
        notes.append("Gmail is connected. Google Drive is missing.")
    elif drive:
        notes.append("Google Drive is connected. Gmail is missing.")
    else:
        notes.append("Neither Gmail nor Google Drive is connected.")

    if not gmail and not drive and not any(doc.get("source_type") == "upload" for doc in documents):
        notes.append("Ask the user to connect Gmail and Google Drive now or upload their PDFs.")

    if any(doc.get("source_type") == "upload" for doc in documents):
        notes.append("Upload fallback is active for at least one document.")

    return notes


def make_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    table = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        table.append("| " + " | ".join(row) + " |")
    return "\n".join(table)


def money(value: Any) -> str:
    if value is None:
        return "TBD"
    return f"${float(value):,.2f}"


def summarize_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return "None"
    parts: list[str] = []
    for key, value in sorted(fields.items()):
        if isinstance(value, (int, float)):
            rendered = money(value)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return "; ".join(parts)


def categorize_expense_vendor(vendor: str | None) -> str:
    if not vendor:
        return "Uncategorized"
    normalized = vendor.lower()
    if any(token in normalized for token in ("anthropic", "openai", "hugging face")):
        return "AI tools"
    if any(token in normalized for token in ("github", "warp", "linear", "exafunction", "windsurf")):
        return "Developer tools"
    if "zoom" in normalized:
        return "Collaboration"
    if any(token in normalized for token in ("delta", "united", "alaska airlines")):
        return "Travel"
    return "Uncategorized"


def normalize_state_code(code: str | None) -> str | None:
    if not code:
        return None
    normalized = code.strip().upper()
    if len(normalized) != 2:
        return None
    return normalized


def resolve_state_support(code: str | None) -> dict[str, str] | None:
    normalized = normalize_state_code(code)
    if not normalized:
        return None
    support = STATE_SUPPORT.get(normalized)
    if support:
        return {"code": normalized, **support}
    return {
        "code": normalized,
        "name": normalized,
        "status": "unconfigured",
        "resident_form": "Unknown",
        "nonresident_form": "Unknown",
        "source_url": "",
    }


def compute_self_employment_summary(
    *,
    tax_year: int,
    filing_status: str,
    wages: float,
    nonemployee_compensation: float,
    business_expenses: float,
    has_business_expenses: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "net_profit": None,
        "net_earnings": None,
        "social_security_taxable_earnings": None,
        "self_employment_tax": None,
        "deductible_half": None,
        "schedule_se_required": False,
        "wage_base": SOCIAL_SECURITY_WAGE_BASE_BY_YEAR.get(tax_year),
        "notes": [],
    }
    if nonemployee_compensation <= 0.0 or not has_business_expenses:
        return summary

    net_profit = nonemployee_compensation - business_expenses
    summary["net_profit"] = net_profit
    if net_profit <= 0.0:
        summary["notes"].append(
            "Net contractor profit is zero or below zero, so no self-employment tax is currently computed."
        )
        return summary

    net_earnings = round(net_profit * SELF_EMPLOYMENT_NET_EARNINGS_FACTOR, 2)
    summary["net_earnings"] = net_earnings
    if net_earnings < SELF_EMPLOYMENT_FILING_THRESHOLD:
        summary["notes"].append(
            "Net earnings from self-employment are below the $400 Schedule SE filing threshold."
        )
        return summary

    wage_base = summary["wage_base"]
    if wage_base is None:
        summary["notes"].append(
            f"Self-employment tax wage-base support is not configured for tax year {tax_year}."
        )
        return summary

    schedule_se_required = True
    remaining_social_security_capacity = max(wage_base - wages, 0.0)
    social_security_taxable_earnings = min(net_earnings, remaining_social_security_capacity)
    social_security_tax = social_security_taxable_earnings * SELF_EMPLOYMENT_SOCIAL_SECURITY_RATE
    medicare_tax = net_earnings * SELF_EMPLOYMENT_MEDICARE_RATE
    self_employment_tax = round(social_security_tax + medicare_tax, 2)

    summary["schedule_se_required"] = schedule_se_required
    summary["social_security_taxable_earnings"] = round(social_security_taxable_earnings, 2)
    summary["self_employment_tax"] = self_employment_tax
    summary["deductible_half"] = round(self_employment_tax / 2.0, 2)

    if wages >= wage_base:
        summary["notes"].append(
            "W-2 wages already reach the 2025 Social Security wage base, so only the Medicare portion of self-employment tax is included."
        )
    elif wages + net_earnings > wage_base:
        summary["notes"].append(
            "W-2 wages partially use the 2025 Social Security wage base, so the Social Security portion of self-employment tax is capped."
        )

    additional_medicare_threshold = ADDITIONAL_MEDICARE_THRESHOLDS.get(filing_status)
    if additional_medicare_threshold is not None and wages + net_earnings > additional_medicare_threshold:
        summary["notes"].append(
            "Additional Medicare Tax may apply above the filing-status threshold and is not yet modeled in this scaffold."
        )

    if filing_status == "married_filing_jointly":
        summary["notes"].append(
            "For MFJ returns, confirm which spouse earned the contractor income because each spouse files a separate Schedule SE when both have self-employment earnings."
        )

    return summary
