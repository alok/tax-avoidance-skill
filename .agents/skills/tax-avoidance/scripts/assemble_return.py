from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tax_flow_common import (  # noqa: E402
    RULE_SOURCES,
    WIKIPEDIA_AVOIDANCE,
    WIKIPEDIA_EVASION,
    dump_json,
    ensure_dir,
    load_json,
    make_markdown_table,
    money,
    summarize_fields,
)


def rule_citations(*keys: str) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for key in keys:
        source = RULE_SOURCES.get(key)
        if source:
            citations.append(source)
    return citations


def fact_value(normalized: dict[str, Any], key: str) -> float:
    return float(normalized["facts"].get(key, {}).get("value", 0.0) or 0.0)


def fact_sources(normalized: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return list(normalized["facts"].get(key, {}).get("sources", []))


def fact_is_known(normalized: dict[str, Any], key: str) -> bool:
    return key in normalized.get("answered_fields", []) or bool(fact_sources(normalized, key))


def build_line_items(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    wages = fact_value(normalized, "wages")
    nonemployee_compensation = fact_value(normalized, "nonemployee_compensation")
    business_expenses = fact_value(normalized, "business_expenses")
    interest = fact_value(normalized, "taxable_interest")
    dividends = fact_value(normalized, "ordinary_dividends")
    capital_gains = fact_value(normalized, "capital_gains")
    social_security = fact_value(normalized, "social_security_benefits")
    taxable_social_security = fact_value(normalized, "taxable_social_security_benefits")
    has_business_expenses = bool(fact_sources(normalized, "business_expenses")) or business_expenses > 0.0
    net_profit = None
    if nonemployee_compensation and has_business_expenses:
        net_profit = nonemployee_compensation - business_expenses

    total_income = wages + interest + dividends + capital_gains + taxable_social_security + (net_profit or 0.0)

    ira = fact_value(normalized, "ira_contribution_deduction")
    hsa = fact_value(normalized, "hsa_deduction")
    student_loan_interest = fact_value(normalized, "student_loan_interest_deduction")
    adjustments_total = ira + hsa + student_loan_interest

    agi = total_income - adjustments_total
    deduction_amount = fact_value(normalized, "deduction_amount")
    qbi_deduction = fact_value(normalized, "qbi_deduction")
    taxable_income = max(agi - deduction_amount - qbi_deduction, 0.0) if deduction_amount else None

    tax_before_credits = fact_value(normalized, "tax_before_credits")
    nonrefundable_credits = (
        fact_value(normalized, "education_credit")
        + fact_value(normalized, "clean_vehicle_credit")
        + fact_value(normalized, "clean_energy_credit")
        + fact_value(normalized, "child_tax_credit")
        + fact_value(normalized, "other_nonrefundable_credits")
    )
    total_tax = max(tax_before_credits - nonrefundable_credits, 0.0) if tax_before_credits else None

    withholding = fact_value(normalized, "federal_withholding")
    other_payments = fact_value(normalized, "other_payments")
    total_payments = withholding + other_payments

    refund = None
    amount_owed = None
    if total_tax is not None:
        if total_payments >= total_tax:
            refund = total_payments - total_tax
        else:
            amount_owed = total_tax - total_payments

    return [
        {
            "form": "Schedule C",
            "line": "1",
            "label": "Gross receipts or sales",
            "value": nonemployee_compensation or None,
            "sources": fact_sources(normalized, "nonemployee_compensation"),
            "rule_citations": rule_citations("nonemployee_compensation", "schedule_c"),
        },
        {
            "form": "Schedule C",
            "line": "28",
            "label": "Total expenses",
            "value": business_expenses if has_business_expenses else None,
            "sources": fact_sources(normalized, "business_expenses"),
            "rule_citations": rule_citations("business_expenses", "schedule_c"),
        },
        {
            "form": "Schedule C",
            "line": "31",
            "label": "Net profit or loss",
            "value": net_profit,
            "sources": fact_sources(normalized, "nonemployee_compensation") + fact_sources(normalized, "business_expenses"),
            "rule_citations": rule_citations("schedule_c", "schedule_se"),
        },
        {
            "form": "Form 1040",
            "line": "1a",
            "label": "Wages, salaries, tips",
            "value": wages or None,
            "sources": fact_sources(normalized, "wages"),
            "rule_citations": rule_citations("wages"),
        },
        {
            "form": "Form 1040",
            "line": "2b",
            "label": "Taxable interest",
            "value": interest or None,
            "sources": fact_sources(normalized, "taxable_interest"),
            "rule_citations": rule_citations("taxable_interest"),
        },
        {
            "form": "Form 1040",
            "line": "3b",
            "label": "Ordinary dividends",
            "value": dividends or None,
            "sources": fact_sources(normalized, "ordinary_dividends"),
            "rule_citations": rule_citations("ordinary_dividends"),
        },
        {
            "form": "Form 1040",
            "line": "6a",
            "label": "Social Security benefits",
            "value": social_security if fact_is_known(normalized, "social_security_benefits") else None,
            "sources": fact_sources(normalized, "social_security_benefits"),
            "rule_citations": rule_citations("social_security_benefits"),
        },
        {
            "form": "Form 1040",
            "line": "6b",
            "label": "Taxable Social Security benefits",
            "value": taxable_social_security if fact_is_known(normalized, "taxable_social_security_benefits") else None,
            "sources": fact_sources(normalized, "taxable_social_security_benefits"),
            "rule_citations": rule_citations("taxable_social_security_benefits"),
        },
        {
            "form": "Form 1040",
            "line": "7",
            "label": "Capital gain or loss",
            "value": capital_gains or None,
            "sources": fact_sources(normalized, "capital_gains"),
            "rule_citations": rule_citations("capital_gains"),
        },
        {
            "form": "Form 1040",
            "line": "9",
            "label": "Total income",
            "value": total_income or None,
            "sources": [],
            "rule_citations": rule_citations(
                "wages",
                "taxable_interest",
                "ordinary_dividends",
                "capital_gains",
                "taxable_social_security_benefits",
                "schedule_c",
            ),
        },
        {
            "form": "Form 1040",
            "line": "10",
            "label": "Adjustments to income",
            "value": adjustments_total or None,
            "sources": fact_sources(normalized, "ira_contribution_deduction")
            + fact_sources(normalized, "hsa_deduction")
            + fact_sources(normalized, "student_loan_interest_deduction"),
            "rule_citations": rule_citations(
                "ira_contribution_deduction",
                "hsa_deduction",
                "student_loan_interest_deduction",
            ),
        },
        {
            "form": "Form 1040",
            "line": "11",
            "label": "Adjusted gross income",
            "value": agi or None,
            "sources": [],
            "rule_citations": rule_citations("wages", "ira_contribution_deduction", "hsa_deduction"),
        },
        {
            "form": "Form 1040",
            "line": "12",
            "label": "Standard or itemized deduction",
            "value": deduction_amount or None,
            "sources": fact_sources(normalized, "deduction_amount"),
            "rule_citations": [],
        },
        {
            "form": "Form 1040",
            "line": "15",
            "label": "Taxable income",
            "value": taxable_income,
            "sources": [],
            "rule_citations": [],
        },
        {
            "form": "Form 1040",
            "line": "16",
            "label": "Tax",
            "value": tax_before_credits or None,
            "sources": fact_sources(normalized, "tax_before_credits"),
            "rule_citations": [],
        },
        {
            "form": "Form 1040",
            "line": "20",
            "label": "Other credits",
            "value": nonrefundable_credits or None,
            "sources": fact_sources(normalized, "education_credit")
            + fact_sources(normalized, "clean_vehicle_credit")
            + fact_sources(normalized, "clean_energy_credit")
            + fact_sources(normalized, "child_tax_credit")
            + fact_sources(normalized, "other_nonrefundable_credits"),
            "rule_citations": rule_citations(
                "education_credit",
                "clean_vehicle_credit",
                "clean_energy_credit",
            ),
        },
        {
            "form": "Form 1040",
            "line": "22",
            "label": "Total tax",
            "value": total_tax,
            "sources": [],
            "rule_citations": [],
        },
        {
            "form": "Form 1040",
            "line": "25a",
            "label": "Federal income tax withheld from Forms W-2",
            "value": withholding or None,
            "sources": fact_sources(normalized, "federal_withholding"),
            "rule_citations": rule_citations("federal_withholding"),
        },
        {
            "form": "Form 1040",
            "line": "33",
            "label": "Total payments",
            "value": total_payments or None,
            "sources": fact_sources(normalized, "federal_withholding") + fact_sources(normalized, "other_payments"),
            "rule_citations": rule_citations("federal_withholding"),
        },
        {
            "form": "Form 1040",
            "line": "34",
            "label": "Refund",
            "value": refund,
            "sources": [],
            "rule_citations": [],
        },
        {
            "form": "Form 1040",
            "line": "37",
            "label": "Amount you owe",
            "value": amount_owed,
            "sources": [],
            "rule_citations": [],
        },
    ]


def build_dossier(normalized: dict[str, Any], line_items: list[dict[str, Any]]) -> str:
    inventory_rows = [
        [
            doc.get("id", "unknown"),
            doc.get("doc_type", "unknown"),
            doc.get("source_type", "unknown"),
            doc.get("source_ref", "unknown"),
            doc.get("content_status", "available"),
            summarize_fields(doc.get("fields", {})),
        ]
        for doc in normalized.get("documents", [])
    ]

    line_rows = [
        [item["form"], item["line"], item["label"], money(item["value"])]
        for item in line_items
    ]
    candidate_business_expenses = fact_value(normalized, "candidate_business_expenses")

    connector_lines = [f"- {note}" for note in normalized.get("connector_notes", [])] or ["- None"]
    missing_lines = [f"- {item}" for item in normalized.get("missing_items", [])] or ["- None"]
    unsupported_lines = [f"- {item}" for item in normalized.get("unsupported_reasons", [])] or ["- None"]
    refusal_lines = [f"- {item}" for item in normalized.get("illegal_reasons", [])] or ["- None"]
    candidate_expense_rows = [
        [
            expense.get("document_date") or "unknown",
            expense.get("vendor") or "Unknown",
            expense.get("category") or "Uncategorized",
            money(expense.get("amount")),
            expense.get("source_ref") or "unknown",
        ]
        for expense in normalized.get("candidate_expense_documents", [])
    ]
    state_summary = normalized.get("state_summary", {})
    state_rows = [
        [
            module.get("code", ""),
            module.get("name", ""),
            module.get("status", ""),
            module.get("resident_form", ""),
            module.get("nonresident_form", ""),
            module.get("source_url", "") or "TBD",
        ]
        for module in state_summary.get("modules", [])
    ]
    state_allocation_rows = [
        [
            allocation.get("state", ""),
            money(allocation.get("wages")),
            money(allocation.get("withholding")),
        ]
        for allocation in state_summary.get("allocations", [])
    ]
    state_follow_up_lines = [f"- {item}" for item in state_summary.get("follow_up", [])] or ["- None"]

    sections = [
        "# Tax Dossier",
        "",
        f"Status: **{normalized['status']}**",
        "",
        f"Legal framing: lawful [tax avoidance]({WIKIPEDIA_AVOIDANCE}) only, not [tax evasion]({WIKIPEDIA_EVASION}).",
        "",
        f"Tax year: {normalized['tax_year']}",
        f"Filing status: {normalized.get('filing_status') or 'TBD'}",
        "",
        "## Connector Notes",
        "",
        *connector_lines,
        "",
        "## Document Inventory",
        "",
        make_markdown_table(
            ["ID", "Type", "Source", "Reference", "Content Status", "Observed Fields"],
            inventory_rows or [["None", "None", "None", "None", "None", "None"]],
        ),
        "",
        "## Draft Federal Lines",
        "",
        make_markdown_table(["Form", "Line", "Label", "Value"], line_rows),
        "",
        "## Candidate Business Expenses",
        "",
        f"- Found candidate expense receipts totaling {money(candidate_business_expenses) if candidate_business_expenses else '$0.00'} that are not yet applied to Schedule C.",
        "",
        make_markdown_table(
            ["Date", "Vendor", "Category", "Amount", "Source"],
            candidate_expense_rows or [["None", "None", "None", "$0.00", "None"]],
        ),
        "",
        "## State Follow-Up",
        "",
        f"- Resident state: {state_summary.get('resident_state') or 'None provided'}",
        f"- Work states: {', '.join(state_summary.get('work_states', [])) or 'None provided'}",
        "",
        make_markdown_table(
            ["Code", "State", "Status", "Resident Form", "Nonresident Form", "Official Source"],
            state_rows or [["None", "None", "None", "None", "None", "None"]],
        ),
        "",
        make_markdown_table(
            ["State", "State Wages", "State Withholding"],
            state_allocation_rows or [["None", "$0.00", "$0.00"]],
        ),
        "",
        *state_follow_up_lines,
        "",
        "## Missing Items",
        "",
        *missing_lines,
        "",
        "## Unsupported Or Risky Items",
        "",
        *unsupported_lines,
        "",
        "## Refusal Notes",
        "",
        *refusal_lines,
    ]
    return "\n".join(sections).strip() + "\n"


def build_federal_lines_markdown(line_items: list[dict[str, Any]]) -> str:
    rows: list[list[str]] = []
    for item in line_items:
        doc_sources = ", ".join(src.get("source_ref", "unknown") for src in item.get("sources", [])) or "TBD"
        rule_sources = ", ".join(src["title"] for src in item.get("rule_citations", [])) or "TBD"
        rows.append(
            [
                item["form"],
                item["line"],
                item["label"],
                money(item["value"]),
                doc_sources,
                rule_sources,
            ]
        )
    return "# Federal Lines\n\n" + make_markdown_table(
        ["Form", "Line", "Label", "Value", "Document Sources", "Rule Sources"],
        rows,
    ) + "\n"


def build_missing_items_markdown(normalized: dict[str, Any]) -> str:
    lines = ["# Missing Items", ""]
    if normalized.get("missing_items"):
        lines.extend(f"- {item}" for item in normalized["missing_items"])
    else:
        lines.append("- None")

    if normalized.get("unsupported_reasons"):
        lines.extend(["", "## Unsupported Complexity", ""])
        lines.extend(f"- {item}" for item in normalized["unsupported_reasons"])

    if normalized.get("illegal_reasons"):
        lines.extend(["", "## Refusal", ""])
        lines.extend(f"- {item}" for item in normalized["illegal_reasons"])
    return "\n".join(lines).strip() + "\n"


def assemble_artifacts(normalized: dict[str, Any]) -> dict[str, Any]:
    line_items = build_line_items(normalized)
    return {
        "return-data.json": normalized,
        "federal-lines.md": build_federal_lines_markdown(line_items),
        "tax-dossier.md": build_dossier(normalized, line_items),
        "missing-items.md": build_missing_items_markdown(normalized),
    }


def write_artifacts(out_dir: Path, artifacts: dict[str, Any]) -> None:
    ensure_dir(out_dir)
    for name, artifact in artifacts.items():
        path = out_dir / name
        if name.endswith(".json"):
            dump_json(path, artifact)
        else:
            path.write_text(str(artifact), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble the draft federal return artifacts.")
    parser.add_argument("--input", required=True, type=Path, help="Normalized JSON input.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory.")
    args = parser.parse_args()

    normalized = load_json(args.input)
    artifacts = assemble_artifacts(normalized)
    write_artifacts(args.out_dir, artifacts)


if __name__ == "__main__":
    main()
