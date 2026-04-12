from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tax_flow_common import (  # noqa: E402
    answer_fact,
    aggregate_numeric,
    categorize_expense_vendor,
    connector_notes,
    detect_illegal_request,
    detect_unsupported,
    dump_json,
    load_json,
    normalize_state_code,
    resolve_state_support,
    safe_float,
)


def build_fact(
    key: str,
    value: float,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {"key": key, "value": value, "sources": sources}


def build_stage(key: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "detail": detail}


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    documents = payload.get("documents", [])
    answers = payload.get("answers", {})
    connectors = payload.get("connectors", {})
    user_request = payload.get("user_request", "")
    tax_year = payload.get("tax_year", 2025)
    state = payload.get("state", {})

    illegal_reasons = detect_illegal_request(user_request)
    unsupported_reasons = detect_unsupported(payload)

    wages, wages_sources = aggregate_numeric(documents, {"W-2"}, "wages")
    withholding, withholding_sources = aggregate_numeric(documents, {"W-2"}, "federal_withholding")
    nonemployee_compensation, nonemployee_compensation_sources = aggregate_numeric(
        documents,
        {"1099-NEC"},
        "nonemployee_compensation",
    )
    interest, interest_sources = aggregate_numeric(documents, {"1099-INT"}, "interest_income")
    dividends, dividends_sources = aggregate_numeric(documents, {"1099-DIV"}, "ordinary_dividends")
    capital_gains, capital_gains_sources = aggregate_numeric(
        documents,
        {"1099-B", "1099-DIV"},
        "capital_gains",
    )
    social_security, social_security_sources = aggregate_numeric(
        documents,
        {"SSA-1099"},
        "benefits",
    )
    mortgage_interest, mortgage_interest_sources = aggregate_numeric(
        documents,
        {"1098"},
        "mortgage_interest",
    )
    student_loan_interest, student_loan_interest_sources = aggregate_numeric(
        documents,
        {"1098-E"},
        "student_loan_interest",
    )
    qualified_tuition, qualified_tuition_sources = aggregate_numeric(
        documents,
        {"1098-T"},
        "qualified_tuition",
    )
    scholarships_and_grants, scholarships_and_grants_sources = aggregate_numeric(
        documents,
        {"1098-T"},
        "scholarships_or_grants",
    )
    expense_documents_for_year = [
        document
        for document in documents
        if document.get("doc_type") == "Expense Receipt"
        and (
            not document.get("document_date")
            or str(document.get("document_date")).startswith(str(tax_year))
        )
    ]
    candidate_business_expenses, candidate_expense_sources = aggregate_numeric(
        expense_documents_for_year,
        {"Expense Receipt"},
        "amount",
    )
    candidate_expense_documents = [
        {
            "id": document.get("id"),
            "source_ref": document.get("source_ref"),
            "source_type": document.get("source_type"),
            "document_date": document.get("document_date"),
            "vendor": document.get("fields", {}).get("vendor", "Unknown"),
            "category": categorize_expense_vendor(document.get("fields", {}).get("vendor")),
            "amount": safe_float(document.get("fields", {}).get("amount")),
        }
        for document in expense_documents_for_year
        if safe_float(document.get("fields", {}).get("amount")) != 0.0
    ]
    charitable_cash, charitable_sources = aggregate_numeric(
        documents,
        {"Donation Receipt"},
        "cash_donations",
    )

    ira_deduction, ira_sources = answer_fact(answers, "ira_contribution_deduction")
    hsa_deduction, hsa_sources = answer_fact(answers, "hsa_deduction")
    business_expenses, business_expense_sources = answer_fact(answers, "business_expenses")
    deduction_amount, deduction_sources = answer_fact(answers, "deduction_amount")
    qbi_deduction, qbi_sources = answer_fact(answers, "qbi_deduction")
    tax_before_credits, tax_before_credits_sources = answer_fact(answers, "tax_before_credits")
    other_payments, other_payments_sources = answer_fact(answers, "other_payments")
    education_credit, education_credit_sources = answer_fact(answers, "education_credit")
    clean_vehicle_credit, clean_vehicle_credit_sources = answer_fact(answers, "clean_vehicle_credit")
    clean_energy_credit, clean_energy_credit_sources = answer_fact(answers, "clean_energy_credit")
    child_tax_credit, child_tax_credit_sources = answer_fact(answers, "child_tax_credit")
    other_nonrefundable_credits, other_credit_sources = answer_fact(
        answers,
        "other_nonrefundable_credits",
    )

    resident_state = normalize_state_code(state.get("resident_state"))
    work_states_raw = state.get("work_states", [])
    work_states: list[str] = []
    for item in work_states_raw:
        normalized = normalize_state_code(item)
        if normalized and normalized not in work_states:
            work_states.append(normalized)
    if resident_state and resident_state not in work_states:
        work_states.insert(0, resident_state)

    state_allocation_totals: dict[str, dict[str, float]] = {}
    for document in documents:
        for allocation in document.get("fields", {}).get("state_allocations", []):
            code = normalize_state_code(allocation.get("state"))
            if not code:
                continue
            bucket = state_allocation_totals.setdefault(code, {"wages": 0.0, "withholding": 0.0})
            bucket["wages"] += safe_float(allocation.get("wages"))
            bucket["withholding"] += safe_float(allocation.get("withholding"))
            if code not in work_states:
                work_states.append(code)

    state_modules = [resolve_state_support(code) for code in work_states]
    state_modules = [module for module in state_modules if module is not None]
    state_follow_up: list[str] = []
    if resident_state:
        resident_module = resolve_state_support(resident_state)
        if resident_module and resident_module["status"] == "planned":
            state_follow_up.append(
                f"{resident_module['name']} state return support is planned but not yet automated. Preserve state withholding and source-income details."
            )
        elif resident_module and resident_module["status"] == "unconfigured":
            state_follow_up.append(
                f"State return support for {resident_module['code']} is not configured yet. Preserve all state documents and withholding details."
            )
    if len(work_states) > 1:
        state_follow_up.append(
            "Multiple work states are present. Preserve state wage sourcing and withholding for resident and nonresident filings."
        )
    if state_allocation_totals and not resident_state:
        state_follow_up.append(
            "State allocations were found on tax documents. Confirm which listed state is your resident state."
        )

    missing_items: list[str] = []
    available_dedupe_keys = {
        document.get("dedupe_key")
        for document in documents
        if document.get("dedupe_key") and document.get("content_status") == "available"
    }
    if not payload.get("filing_status"):
        missing_items.append("Confirm the filing status for the return.")
    if not documents:
        missing_items.append("Upload or connect at least one tax document before continuing.")
    if deduction_amount == 0.0 and "deduction_amount" not in answers:
        missing_items.append("Choose the deduction path and provide the deduction amount to use in the draft package.")
    if tax_before_credits == 0.0 and "tax_before_credits" not in answers:
        missing_items.append("Provide a tax-before-credits figure or leave the tax lines marked for review.")
    if nonemployee_compensation > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            "Provide deductible business expenses for the 1099-NEC work, or explicitly confirm that business expenses should be treated as zero."
        )
    if candidate_business_expenses > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            f"Review and confirm the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} before applying them to Schedule C."
        )
    for note in state_follow_up:
        if note not in missing_items:
            missing_items.append(note)
    if any(doc.get("doc_type") == "1099-B" and "capital_gains" not in doc.get("fields", {}) for doc in documents):
        missing_items.append("Summarize net capital gains or losses from the 1099-B support documents.")
    has_1098t = any(doc.get("doc_type") == "1098-T" for doc in documents)
    if has_1098t and "education_credit" not in answers:
        if qualified_tuition > 0.0 or scholarships_and_grants > 0.0:
            missing_items.append(
                "Review the 1098-T tuition and scholarship amounts and confirm the creditable qualified education expenses before applying an education credit."
            )
        else:
            missing_items.append(
                "Extract the key 1098-T amounts or upload a clearer copy before reviewing any education credit."
            )
    for document in documents:
        content_status = document.get("content_status")
        doc_type = document.get("doc_type", "document")
        source_ref = document.get("source_ref", "unknown source")
        dedupe_key = document.get("dedupe_key")
        if dedupe_key and dedupe_key in available_dedupe_keys and content_status != "available":
            continue
        if content_status == "portal_notice_only":
            missing_items.append(
                f"Download the actual {doc_type} from {source_ref}; the current source is only a portal or availability notice."
            )
        elif content_status == "unreadable_encrypted_attachment":
            missing_items.append(
                f"Open or upload the actual {doc_type} from {source_ref}; the attachment exists but its contents were not readable in this workflow."
            )
        elif content_status == "metadata_only":
            if document.get("fields"):
                missing_items.append(
                    f"Confirm the extracted {doc_type} details from {source_ref} against the actual filed form or PDF before using them in a return draft."
                )
            else:
                missing_items.append(
                    f"Provide the actual contents for {doc_type} from {source_ref}; only metadata is available right now."
                )

    status = "ok"
    if illegal_reasons:
        status = "refused"
    elif unsupported_reasons:
        status = "unsupported"

    non_w2_income_docs = {
        "1099-INT",
        "1099-DIV",
        "1099-B",
        "1099-NEC",
        "SSA-1099",
    }
    income_doc_count = sum(
        1
        for document in documents
        if document.get("doc_type") == "W-2" or document.get("doc_type") in non_w2_income_docs
    )
    incomplete_documents = [
        document
        for document in documents
        if document.get("content_status") in {"portal_notice_only", "unreadable_encrypted_attachment", "metadata_only"}
        and not (
            document.get("dedupe_key")
            and document.get("dedupe_key") in available_dedupe_keys
            and document.get("content_status") != "available"
        )
    ]

    source_status = "complete" if documents or connectors.get("gmail") or connectors.get("google_drive") else "pending"
    if documents:
        source_detail = f"{len(documents)} document(s) are already in the intake queue."
    elif connectors.get("gmail") or connectors.get("google_drive"):
        source_detail = "Connectors are available, but no tax documents have been gathered yet."
    else:
        source_detail = "Connect Gmail and Google Drive or upload PDFs to start the intake."

    filing_status_status = "complete" if payload.get("filing_status") else "pending"
    filing_status_detail = (
        f"Filing status is set to {payload.get('filing_status')}."
        if payload.get("filing_status")
        else "Confirm the filing status before drafting the return."
    )

    income_status = "complete" if income_doc_count else "pending"
    income_detail = (
        f"Found {income_doc_count} income document(s) across wage, contractor, investment, or benefit flows."
        if income_doc_count
        else "Gather at least one W-2, 1099, or SSA-1099 before continuing."
    )

    deduction_status = "complete" if "deduction_amount" in answers else "pending"
    deduction_detail = (
        f"Deduction amount is captured at ${deduction_amount:,.2f}."
        if "deduction_amount" in answers
        else "Choose the deduction path and capture the deduction amount."
    )

    tax_review_status = "complete" if "tax_before_credits" in answers else "pending"
    tax_review_detail = (
        f"Tax-before-credits is captured at ${tax_before_credits:,.2f}."
        if "tax_before_credits" in answers
        else "Capture a tax-before-credits figure or leave the draft marked for manual review."
    )

    if nonemployee_compensation > 0.0:
        self_employment_status = "complete" if "business_expenses" in answers else "pending"
        self_employment_detail = (
            f"Schedule C expenses are captured at ${business_expenses:,.2f}."
            if "business_expenses" in answers
            else "1099-NEC income is present. Confirm deductible business expenses or explicitly set them to zero."
        )
    else:
        self_employment_status = "not_needed"
        self_employment_detail = "No 1099-NEC self-employment income was detected."

    if has_1098t:
        education_status = "complete" if "education_credit" in answers else "pending"
        education_detail = (
            f"Education credit is currently set to ${education_credit:,.2f}."
            if "education_credit" in answers
            else "1098-T documents are present. Review qualified tuition and scholarship figures before applying a credit."
        )
    else:
        education_status = "not_needed"
        education_detail = "No 1098-T education-credit workflow was detected."

    state_status = "complete" if resident_state and not state_follow_up else "pending"
    if resident_state and not state_follow_up:
        state_detail = f"Resident state context is captured as {resident_state} with no open state follow-up."
    elif resident_state or work_states or state_allocation_totals:
        state_detail = "State context exists, but resident/work-state follow-up is still open."
    else:
        state_detail = "Capture resident state and any work states early so state filing follow-up stays visible."

    document_follow_up_status = "pending" if incomplete_documents else "complete"
    document_follow_up_detail = (
        f"{len(incomplete_documents)} document(s) still need a clearer PDF, full attachment, or confirmation against the source form."
        if incomplete_documents
        else "All queued documents are available in a usable form for this draft."
    )

    workflow_stages = [
        build_stage("source_access", "Source Access", source_status, source_detail),
        build_stage("filing_status", "Filing Status", filing_status_status, filing_status_detail),
        build_stage("income_documents", "Income Documents", income_status, income_detail),
        build_stage("deduction_review", "Deduction Review", deduction_status, deduction_detail),
        build_stage("tax_review", "Tax Review", tax_review_status, tax_review_detail),
        build_stage("self_employment", "Self-Employment Review", self_employment_status, self_employment_detail),
        build_stage("education_credit", "Education Credit Review", education_status, education_detail),
        build_stage("state_scaffolding", "State Scaffolding", state_status, state_detail),
        build_stage("document_follow_up", "Document Follow-Up", document_follow_up_status, document_follow_up_detail),
    ]

    facts = {
        "wages": build_fact("wages", wages, wages_sources),
        "nonemployee_compensation": build_fact(
            "nonemployee_compensation",
            nonemployee_compensation,
            nonemployee_compensation_sources,
        ),
        "federal_withholding": build_fact("federal_withholding", withholding, withholding_sources),
        "taxable_interest": build_fact("taxable_interest", interest, interest_sources),
        "ordinary_dividends": build_fact("ordinary_dividends", dividends, dividends_sources),
        "capital_gains": build_fact("capital_gains", capital_gains, capital_gains_sources),
        "social_security_benefits": build_fact("social_security_benefits", social_security, social_security_sources),
        "mortgage_interest": build_fact("mortgage_interest", mortgage_interest, mortgage_interest_sources),
        "student_loan_interest_deduction": build_fact(
            "student_loan_interest_deduction",
            student_loan_interest,
            student_loan_interest_sources,
        ),
        "qualified_tuition": build_fact(
            "qualified_tuition",
            qualified_tuition,
            qualified_tuition_sources,
        ),
        "scholarships_and_grants": build_fact(
            "scholarships_and_grants",
            scholarships_and_grants,
            scholarships_and_grants_sources,
        ),
        "candidate_business_expenses": build_fact(
            "candidate_business_expenses",
            candidate_business_expenses,
            candidate_expense_sources,
        ),
        "charitable_cash": build_fact("charitable_cash", charitable_cash, charitable_sources),
        "ira_contribution_deduction": build_fact("ira_contribution_deduction", ira_deduction, ira_sources),
        "hsa_deduction": build_fact("hsa_deduction", hsa_deduction, hsa_sources),
        "business_expenses": build_fact("business_expenses", business_expenses, business_expense_sources),
        "deduction_amount": build_fact("deduction_amount", deduction_amount, deduction_sources),
        "qbi_deduction": build_fact("qbi_deduction", qbi_deduction, qbi_sources),
        "tax_before_credits": build_fact("tax_before_credits", tax_before_credits, tax_before_credits_sources),
        "other_payments": build_fact("other_payments", other_payments, other_payments_sources),
        "education_credit": build_fact("education_credit", education_credit, education_credit_sources),
        "clean_vehicle_credit": build_fact("clean_vehicle_credit", clean_vehicle_credit, clean_vehicle_credit_sources),
        "clean_energy_credit": build_fact("clean_energy_credit", clean_energy_credit, clean_energy_credit_sources),
        "child_tax_credit": build_fact("child_tax_credit", child_tax_credit, child_tax_credit_sources),
        "other_nonrefundable_credits": build_fact(
            "other_nonrefundable_credits",
            other_nonrefundable_credits,
            other_credit_sources,
        ),
    }

    normalized: dict[str, Any] = {
        "status": status,
        "tax_year": tax_year,
        "filing_status": payload.get("filing_status", ""),
        "user_request": user_request,
        "documents": documents,
        "connectors": connectors,
        "connector_notes": connector_notes(connectors, documents),
        "illegal_reasons": illegal_reasons,
        "unsupported_reasons": unsupported_reasons,
        "missing_items": missing_items,
        "state_summary": {
            "resident_state": resident_state,
            "work_states": work_states,
            "modules": state_modules,
            "follow_up": state_follow_up,
            "allocations": [
                {
                    "state": code,
                    "wages": totals["wages"],
                    "withholding": totals["withholding"],
                }
                for code, totals in sorted(state_allocation_totals.items())
            ],
        },
        "workflow_summary": {
            "completed_stage_count": sum(1 for stage in workflow_stages if stage["status"] == "complete"),
            "pending_stage_count": sum(1 for stage in workflow_stages if stage["status"] == "pending"),
            "not_needed_stage_count": sum(1 for stage in workflow_stages if stage["status"] == "not_needed"),
            "stages": workflow_stages,
        },
        "candidate_expense_documents": candidate_expense_documents,
        "facts": facts,
    }
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize tax documents into structured facts.")
    parser.add_argument("--input", required=True, type=Path, help="Input JSON payload.")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path.")
    args = parser.parse_args()

    payload = load_json(args.input)
    normalized = normalize_payload(payload)
    dump_json(args.output, normalized)


if __name__ == "__main__":
    main()
