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


def add_interview_question(
    questions: list[dict[str, Any]],
    seen_ids: set[str],
    *,
    question_id: str,
    priority: int,
    prompt: str,
    why_needed: str,
    blocker: bool,
    source_hints: list[str] | None = None,
) -> None:
    if question_id in seen_ids:
        return
    questions.append(
        {
            "id": question_id,
            "priority": priority,
            "prompt": prompt,
            "why_needed": why_needed,
            "blocker": blocker,
            "source_hints": source_hints or [],
        }
    )
    seen_ids.add(question_id)


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
    interview_questions: list[dict[str, Any]] = []
    seen_question_ids: set[str] = set()
    available_dedupe_keys = {
        document.get("dedupe_key")
        for document in documents
        if document.get("dedupe_key") and document.get("content_status") == "available"
    }
    if not payload.get("filing_status"):
        missing_items.append("Confirm the filing status for the return.")
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="filing_status",
            priority=10,
            prompt="What filing status should this 2025 federal return use: single or married filing jointly?",
            why_needed="The filing status determines whether the return is supported and affects deduction and line calculations.",
            blocker=True,
            source_hints=["Ask the taxpayer directly before drafting Form 1040 lines."],
        )
    if not documents:
        missing_items.append("Upload or connect at least one tax document before continuing.")
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="document_source",
            priority=10,
            prompt="Can you connect Gmail or Google Drive now, or upload at least one actual tax PDF to start the return package?",
            why_needed="The workflow cannot build a reliable document inventory or prefilled draft without at least one source document.",
            blocker=True,
            source_hints=["Preferred sources: Gmail, Google Drive, or direct PDF upload."],
        )
    if deduction_amount == 0.0 and "deduction_amount" not in answers:
        missing_items.append("Choose the deduction path and provide the deduction amount to use in the draft package.")
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="deduction_amount",
            priority=20,
            prompt="What deduction amount should the draft use for 2025: standard deduction or a confirmed itemized total?",
            why_needed="Form 1040 taxable income cannot be drafted without a deduction amount.",
            blocker=True,
            source_hints=["If itemizing, gather the underlying support before locking the amount."],
        )
    if tax_before_credits == 0.0 and "tax_before_credits" not in answers:
        missing_items.append("Provide a tax-before-credits figure or leave the tax lines marked for review.")
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="tax_before_credits",
            priority=30,
            prompt="Do you have a tax-before-credits figure to plug into the draft, or should Form 1040 tax lines stay marked for review?",
            why_needed="Refund and amount-owed estimates depend on the pre-credit tax figure in this simplified flow.",
            blocker=False,
            source_hints=["Leave blank if you want the package to stay in review mode for tax computation."],
        )
    if nonemployee_compensation > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            "Provide deductible business expenses for the 1099-NEC work, or explicitly confirm that business expenses should be treated as zero."
        )
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="business_expenses",
            priority=20,
            prompt="What deductible business expenses should be applied to the 1099-NEC work, or should the draft treat business expenses as zero?",
            why_needed="Schedule C net profit should not be drafted from gross receipts alone if deductible expenses still need confirmation.",
            blocker=True,
            source_hints=["Use receipts, bookkeeping totals, or an explicit zero-expense confirmation."],
        )
    if candidate_business_expenses > 0.0 and "business_expenses" not in answers:
        missing_items.append(
            f"Review and confirm the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} before applying them to Schedule C."
        )
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="candidate_business_expenses",
            priority=25,
            prompt=f"Should the candidate business-expense receipts totaling ${candidate_business_expenses:,.2f} be included in Schedule C, excluded, or reviewed one by one?",
            why_needed="Receipts are surfaced as candidates only and should not become deductions without confirmation.",
            blocker=False,
            source_hints=[
                "Review the candidate expense table in the dossier.",
                "Confirm whether each vendor was actually business-related.",
            ],
        )
    for note in state_follow_up:
        if note not in missing_items:
            missing_items.append(note)
    if state_allocation_totals and not resident_state:
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="resident_state",
            priority=20,
            prompt="Which state was your resident state for the 2025 return?",
            why_needed="State withholding and sourcing details are present, but resident-state context is still missing.",
            blocker=False,
            source_hints=["Use the W-2 state boxes or the taxpayer's year-end residence."],
        )
    if any(doc.get("doc_type") == "1099-B" and "capital_gains" not in doc.get("fields", {}) for doc in documents):
        missing_items.append("Summarize net capital gains or losses from the 1099-B support documents.")
        add_interview_question(
            interview_questions,
            seen_question_ids,
            question_id="capital_gains_summary",
            priority=20,
            prompt="What net capital gain or loss summary should the draft use from the 1099-B support documents?",
            why_needed="The simplified flow supports summarized capital gains, but it still needs the net figure.",
            blocker=True,
            source_hints=["Use a broker gain/loss summary or a reviewed 1099-B worksheet total."],
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
            add_interview_question(
                interview_questions,
                seen_question_ids,
                question_id=f"upload:{document.get('id', source_ref)}",
                priority=10,
                prompt=f"Please upload or fetch the actual {doc_type} from {source_ref} instead of the portal notice.",
                why_needed="A portal notice does not provide the underlying tax form values needed for the draft package.",
                blocker=True,
                source_hints=["Use the downloadable PDF or the official account statement."],
            )
        elif content_status == "unreadable_encrypted_attachment":
            missing_items.append(
                f"Open or upload the actual {doc_type} from {source_ref}; the attachment exists but its contents were not readable in this workflow."
            )
            add_interview_question(
                interview_questions,
                seen_question_ids,
                question_id=f"decrypt:{document.get('id', source_ref)}",
                priority=10,
                prompt=f"Can you upload an unlocked copy of the {doc_type} from {source_ref} or share the needed figures manually?",
                why_needed="The workflow found the attachment but could not read the tax form contents.",
                blocker=True,
                source_hints=["Unlocked PDF preferred; manual line-item entry is second best."],
            )
        elif content_status == "metadata_only":
            if document.get("fields"):
                missing_items.append(
                    f"Confirm the extracted {doc_type} details from {source_ref} against the actual filed form or PDF before using them in a return draft."
                )
                add_interview_question(
                    interview_questions,
                    seen_question_ids,
                    question_id=f"confirm:{document.get('id', source_ref)}",
                    priority=15,
                    prompt=f"Can you confirm the extracted {doc_type} details from {source_ref} against the actual form or PDF?",
                    why_needed="The workflow only has metadata-level extraction for this document and needs user confirmation before relying on it.",
                    blocker=False,
                    source_hints=["Open the actual PDF and verify the captured line items."],
                )
            else:
                missing_items.append(
                    f"Provide the actual contents for {doc_type} from {source_ref}; only metadata is available right now."
                )
                add_interview_question(
                    interview_questions,
                    seen_question_ids,
                    question_id=f"contents:{document.get('id', source_ref)}",
                    priority=10,
                    prompt=f"Please provide the actual contents for the {doc_type} from {source_ref}.",
                    why_needed="Only metadata is available, so the workflow does not yet have usable tax values.",
                    blocker=True,
                    source_hints=["Upload the PDF or enter the line-item figures manually."],
                )

    interview_questions.sort(key=lambda item: (item["priority"], item["id"]))

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
        "interview_questions": interview_questions,
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
