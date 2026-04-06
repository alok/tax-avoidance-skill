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


def make_interview_question(
    question_id: str,
    prompt: str,
    rationale: str,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = []
    for source_ref in source_refs or []:
        if source_ref and source_ref not in refs:
            refs.append(source_ref)
    return {
        "id": question_id,
        "prompt": prompt,
        "rationale": rationale,
        "source_refs": refs,
    }


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
    next_questions: list[dict[str, Any]] = []
    available_dedupe_keys = {
        document.get("dedupe_key")
        for document in documents
        if document.get("dedupe_key") and document.get("content_status") == "available"
    }
    if not payload.get("filing_status"):
        missing_items.append("Confirm the filing status for the return.")
        next_questions.append(
            make_interview_question(
                "filing-status",
                "What filing status should this draft use: single or married filing jointly?",
                "The filing status drives the deduction, tax brackets, and which downstream interview steps apply.",
            )
        )
    if not documents:
        missing_items.append("Upload or connect at least one tax document before continuing.")
        next_questions.append(
            make_interview_question(
                "document-intake",
                "Can you connect Gmail and Google Drive or upload at least one tax form PDF to start the draft?",
                "The workflow cannot assemble a return package without at least one primary tax document.",
            )
        )
    if deduction_amount == 0.0 and "deduction_amount" not in answers:
        deduction_prompt = "Choose the deduction path and provide the deduction amount to use in the draft package."
        deduction_refs: list[str] = []
        itemized_clues: list[str] = []
        if mortgage_interest > 0.0:
            itemized_clues.append(f"mortgage interest of ${mortgage_interest:,.2f}")
            deduction_refs.extend(source.get("source_ref", "") for source in mortgage_interest_sources)
        if charitable_cash > 0.0:
            itemized_clues.append(f"cash donations of ${charitable_cash:,.2f}")
            deduction_refs.extend(source.get("source_ref", "") for source in charitable_sources)
        if student_loan_interest > 0.0:
            deduction_refs.extend(source.get("source_ref", "") for source in student_loan_interest_sources)
        if itemized_clues:
            deduction_prompt = (
                "Choose whether this draft should use the standard deduction or an itemized deduction, "
                f"then provide the amount to carry on Form 1040 line 12. Current document clues show {' and '.join(itemized_clues)}."
            )
        missing_items.append(deduction_prompt)
        next_questions.append(
            make_interview_question(
                "deduction-amount",
                deduction_prompt,
                "The draft package cannot finish taxable income without a deduction amount. Mortgage-interest or donation documents may justify an itemized path.",
                deduction_refs,
            )
        )
    if tax_before_credits == 0.0 and "tax_before_credits" not in answers:
        missing_items.append("Provide a tax-before-credits figure or leave the tax lines marked for review.")
        next_questions.append(
            make_interview_question(
                "tax-before-credits",
                "Do you want to supply a tax-before-credits figure now, or should this draft leave Form 1040 tax lines marked for manual review?",
                "This repo assembles a prefilled package, but it does not yet compute the full tax from first principles.",
            )
        )
    if nonemployee_compensation > 0.0 and "business_expenses" not in answers:
        schedule_c_prompt = (
            "Provide deductible business expenses for the 1099-NEC work, or explicitly confirm that business expenses should be treated as zero."
        )
        missing_items.append(schedule_c_prompt)
        next_questions.append(
            make_interview_question(
                "schedule-c-expenses",
                schedule_c_prompt,
                "Schedule C net profit cannot be drafted safely until the workflow knows whether deductible expenses exist.",
                [source.get("source_ref", "") for source in nonemployee_compensation_sources],
            )
        )
    if candidate_business_expenses > 0.0 and "business_expenses" not in answers:
        review_prompt = (
            f"Review and confirm the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} before applying them to Schedule C."
        )
        missing_items.append(review_prompt)
        next_questions.append(
            make_interview_question(
                "candidate-business-expenses",
                review_prompt,
                "The workflow found likely business receipts, but it should not silently turn them into deductions without user confirmation.",
                [source.get("source_ref", "") for source in candidate_expense_sources],
            )
        )
    for note in state_follow_up:
        if note not in missing_items:
            missing_items.append(note)
    if len(work_states) > 1:
        next_questions.append(
            make_interview_question(
                "state-follow-up",
                "Which state is your resident return, and should the draft preserve separate wage sourcing for each listed work state?",
                "Multistate context is stored now so a later state-return flow can reuse the withholding and sourcing details.",
                work_states,
            )
        )
    if any(doc.get("doc_type") == "1099-B" and "capital_gains" not in doc.get("fields", {}) for doc in documents):
        missing_items.append("Summarize net capital gains or losses from the 1099-B support documents.")
        next_questions.append(
            make_interview_question(
                "capital-gains-summary",
                "What net capital gain or loss should this draft use from the 1099-B support documents?",
                "Brokerage packages often need a summarized capital-gains figure before Form 1040 line 7 can be drafted.",
                [
                    document.get("source_ref", "")
                    for document in documents
                    if document.get("doc_type") == "1099-B"
                ],
            )
        )
    for document in documents:
        content_status = document.get("content_status")
        doc_type = document.get("doc_type", "document")
        source_ref = document.get("source_ref", "unknown source")
        dedupe_key = document.get("dedupe_key")
        if dedupe_key and dedupe_key in available_dedupe_keys and content_status != "available":
            continue
        if content_status == "portal_notice_only":
            prompt = (
                f"Download the actual {doc_type} from {source_ref}; the current source is only a portal or availability notice."
            )
            missing_items.append(prompt)
            next_questions.append(
                make_interview_question(
                    f"document-{document.get('id', 'unknown')}",
                    prompt,
                    "A portal notice proves the form exists, but the draft needs the actual numbers from the underlying PDF or statement.",
                    [source_ref],
                )
            )
        elif content_status == "unreadable_encrypted_attachment":
            prompt = (
                f"Open or upload the actual {doc_type} from {source_ref}; the attachment exists but its contents were not readable in this workflow."
            )
            missing_items.append(prompt)
            next_questions.append(
                make_interview_question(
                    f"document-{document.get('id', 'unknown')}",
                    prompt,
                    "The workflow found the attachment but could not read the figures, so the actual document still needs a human-visible copy.",
                    [source_ref],
                )
            )
        elif content_status == "metadata_only":
            if document.get("fields"):
                prompt = (
                    f"Confirm the extracted {doc_type} details from {source_ref} against the actual filed form or PDF before using them in a return draft."
                )
                missing_items.append(prompt)
                next_questions.append(
                    make_interview_question(
                        f"document-{document.get('id', 'unknown')}",
                        prompt,
                        "Metadata can be directionally useful, but the final draft should still be checked against the actual form.",
                        [source_ref],
                    )
                )
            else:
                prompt = f"Provide the actual contents for {doc_type} from {source_ref}; only metadata is available right now."
                missing_items.append(prompt)
                next_questions.append(
                    make_interview_question(
                        f"document-{document.get('id', 'unknown')}",
                        prompt,
                        "The workflow knows the document exists, but it still needs the actual figures before they can be used in the draft.",
                        [source_ref],
                    )
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
        "student_loan_interest_deduction": build_fact(
            "student_loan_interest_deduction",
            student_loan_interest,
            student_loan_interest_sources,
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
        "next_questions": next_questions,
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
