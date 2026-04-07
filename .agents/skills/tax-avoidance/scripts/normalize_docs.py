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


def build_interview_question(
    question_id: str,
    prompt: str,
    why_it_matters: str,
    evidence: list[dict[str, Any]],
    priority: int,
) -> dict[str, Any]:
    return {
        "id": question_id,
        "prompt": prompt,
        "why_it_matters": why_it_matters,
        "evidence": evidence,
        "priority": priority,
    }


def doc_evidence(
    documents: list[dict[str, Any]],
    doc_types: set[str],
    field_name: str | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for document in documents:
        if document.get("doc_type") not in doc_types:
            continue
        if field_name is not None and field_name not in document.get("fields", {}):
            continue
        evidence.append(
            {
                "doc_id": document.get("id"),
                "doc_type": document.get("doc_type"),
                "source_ref": document.get("source_ref"),
            }
        )
    return evidence


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
    observed_student_loan_interest, observed_student_loan_interest_sources = aggregate_numeric(
        documents,
        {"1098-E"},
        "student_loan_interest",
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
    student_loan_interest_deduction, student_loan_interest_deduction_sources = answer_fact(
        answers,
        "student_loan_interest_deduction",
    )
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
    interview_questions: list[dict[str, Any]] = []
    available_dedupe_keys = {
        document.get("dedupe_key")
        for document in documents
        if document.get("dedupe_key") and document.get("content_status") == "available"
    }
    if not payload.get("filing_status"):
        missing_items.append("Confirm the filing status for the return.")
        interview_questions.append(
            build_interview_question(
                "filing-status",
                "What filing status should this draft use: single or married filing jointly?",
                "Filing status changes the supported return path and deduction assumptions.",
                [],
                10,
            )
        )
    if not documents:
        missing_items.append("Upload or connect at least one tax document before continuing.")
    if deduction_amount == 0.0 and "deduction_amount" not in answers:
        missing_items.append("Choose the deduction path and provide the deduction amount to use in the draft package.")
        deduction_evidence = doc_evidence(documents, {"1098", "Donation Receipt"})
        interview_questions.append(
            build_interview_question(
                "deduction-path",
                (
                    "Should this draft use the standard deduction, or do you want to itemize using "
                    "the mortgage-interest and donation documents already found?"
                    if deduction_evidence
                    else "Should this draft use the standard deduction, or do you want to itemize?"
                ),
                (
                    "This controls Form 1040 line 12 and whether itemized-support documents should "
                    "change the draft return."
                    if deduction_evidence
                    else "This controls Form 1040 line 12 and the taxable-income draft."
                ),
                deduction_evidence,
                9,
            )
        )
    if tax_before_credits == 0.0 and "tax_before_credits" not in answers:
        missing_items.append("Provide a tax-before-credits figure or leave the tax lines marked for review.")
        interview_questions.append(
            build_interview_question(
                "tax-before-credits",
                "Do you already have a provisional tax-before-credits figure from a worksheet or other software, or should the tax lines stay marked for review?",
                "The draft can assemble income and payment lines without this number, but refund or balance-due output stays provisional until it is supplied.",
                [],
                4,
            )
        )
    if nonemployee_compensation > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            "Provide deductible business expenses for the 1099-NEC work, or explicitly confirm that business expenses should be treated as zero."
        )
        nec_evidence = doc_evidence(documents, {"1099-NEC"})
        question_prompt = (
            f"Which of the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} are actually deductible for the 1099-NEC work, and are there any others to add?"
            if candidate_business_expenses > 0.0
            else "What deductible business expenses should be used for the 1099-NEC work, or should this draft explicitly treat them as zero?"
        )
        question_evidence = nec_evidence
        if candidate_business_expenses > 0.0:
            question_evidence += doc_evidence(documents, {"Expense Receipt"}, "amount")
        interview_questions.append(
            build_interview_question(
                "business-expenses-confirmation",
                question_prompt,
                "Schedule C net profit cannot be finalized until business expenses are confirmed or explicitly set to zero.",
                question_evidence,
                10,
            )
        )
    if candidate_business_expenses > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            f"Review and confirm the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} before applying them to Schedule C."
        )
    if state_allocation_totals and not resident_state:
        interview_questions.append(
            build_interview_question(
                "resident-state",
                "Which listed state was your resident state for the tax year?",
                "Resident state determines which state return should anchor the later handoff, especially when multiple state wage allocations were found.",
                doc_evidence(documents, {"W-2"}, "state_allocations"),
                8,
            )
        )
    if observed_student_loan_interest > 0.0 and "student_loan_interest_deduction" not in answers:
        interview_questions.append(
            build_interview_question(
                "student-loan-interest",
                f"The 1098-E documents show ${observed_student_loan_interest:,.2f} of student loan interest. Should this amount be carried into the draft return?",
                "Student loan interest can affect the income adjustments section when the form amount is confirmed as deductible.",
                doc_evidence(documents, {"1098-E"}, "student_loan_interest"),
                7,
            )
        )
    if charitable_cash > 0.0 and "deduction_amount" not in answers:
        interview_questions.append(
            build_interview_question(
                "charitable-giving",
                f"The donation receipts show ${charitable_cash:,.2f} of cash gifts. Do you want those considered as part of an itemized-deduction path?",
                "Donation receipts matter only if the return is being prepared on an itemized basis.",
                doc_evidence(documents, {"Donation Receipt"}, "cash_donations"),
                6,
            )
        )
    if any(document.get("doc_type") == "5498" for document in documents) and "ira_contribution_deduction" not in answers:
        interview_questions.append(
            build_interview_question(
                "ira-deduction",
                "A Form 5498 was found. How much of the IRA contribution should be treated as deductible for this draft return?",
                "IRA contribution documents establish that a contribution happened, but the deductible amount still needs user confirmation for the draft package.",
                doc_evidence(documents, {"5498"}),
                7,
            )
        )
    if any(document.get("doc_type") == "1098-T" for document in documents) and "education_credit" not in answers:
        interview_questions.append(
            build_interview_question(
                "education-credit",
                "A Form 1098-T was found. Do you want this workflow to draft an education-credit review, and if so what provisional credit amount or qualified-expense summary should it use?",
                "Education-credit workflows need an explicit review decision before the credit is carried onto the federal draft.",
                doc_evidence(documents, {"1098-T"}),
                7,
            )
        )
    for note in state_follow_up:
        if note not in missing_items:
            missing_items.append(note)
    if any(doc.get("doc_type") == "1099-B" and "capital_gains" not in doc.get("fields", {}) for doc in documents):
        missing_items.append("Summarize net capital gains or losses from the 1099-B support documents.")
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
        "observed_student_loan_interest": build_fact(
            "observed_student_loan_interest",
            observed_student_loan_interest,
            observed_student_loan_interest_sources,
        ),
        "student_loan_interest_deduction": build_fact(
            "student_loan_interest_deduction",
            student_loan_interest_deduction,
            student_loan_interest_deduction_sources,
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
        "interview_questions": sorted(interview_questions, key=lambda item: (-item["priority"], item["id"])),
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
