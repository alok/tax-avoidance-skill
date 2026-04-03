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
    money,
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


def build_question(
    question_id: str,
    prompt: str,
    response_type: str,
    required_for: list[str],
    reason: str,
    priority: int,
    *,
    blocking: bool = True,
    options: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    question: dict[str, Any] = {
        "id": question_id,
        "priority": priority,
        "blocking": blocking,
        "prompt": prompt,
        "response_type": response_type,
        "required_for": required_for,
        "reason": reason,
    }
    if options:
        question["options"] = options
    if evidence:
        question["evidence"] = evidence
    return question


def build_interview_questions(
    payload: dict[str, Any],
    *,
    tax_year: int,
    illegal_reasons: list[str],
    unsupported_reasons: list[str],
    missing_items: list[str],
    resident_state: str | None,
    work_states: list[str],
    nonemployee_compensation: float,
    business_expenses: float,
    candidate_business_expenses: float,
    candidate_expense_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if illegal_reasons:
        return []

    questions: list[dict[str, Any]] = []
    documents = payload.get("documents", [])
    answers = payload.get("answers", {})
    connectors = payload.get("connectors", {})

    if not payload.get("filing_status"):
        questions.append(
            build_question(
                "filing-status",
                "What filing status should this return use?",
                "single_choice",
                ["supported return gating", "Form 1040 line mapping"],
                "The deterministic draft only supports single and married filing jointly returns.",
                10,
                options=["single", "married_filing_jointly"],
            )
        )

    if not resident_state:
        questions.append(
            build_question(
                "resident-state",
                f"What was your resident state for the {tax_year} return?",
                "state_code",
                ["state intake scaffolding", "state follow-up notes"],
                "The repo preserves resident-state context now so later state modules do not need the user to reconstruct it.",
                20,
            )
        )

    if not work_states:
        questions.append(
            build_question(
                "work-states",
                f"Did you work or earn wages in any state other than your resident state during {tax_year}?",
                "state_list",
                ["state intake scaffolding"],
                "Work-state context changes later state filing follow-up and prevents losing sourcing information.",
                25,
                blocking=False,
            )
        )

    if "deduction_amount" not in answers:
        questions.append(
            build_question(
                "deduction-amount",
                "Should the draft use the standard deduction or an itemized deduction amount, and what dollar amount should it use?",
                "choice_plus_amount",
                ["Form 1040 lines 12 and 15", "refund or amount-owed estimate"],
                "Taxable income cannot be computed without a deduction path and amount.",
                30,
                options=["standard", "itemized"],
            )
        )

    if "tax_before_credits" not in answers:
        questions.append(
            build_question(
                "tax-before-credits",
                "Do you want to provide a tax-before-credits figure for the draft, or should the tax and refund lines stay marked for review?",
                "number_or_skip",
                ["Form 1040 lines 16, 22, 34, and 37"],
                "The current deterministic draft can preserve line mapping without inventing a tax calculation.",
                40,
                blocking=False,
            )
        )

    if nonemployee_compensation > 0.0 and "business_expenses" not in answers:
        candidate_evidence = [
            f"{expense['vendor']} {money(expense['amount'])} on {expense.get('document_date') or 'unknown date'}"
            for expense in candidate_expense_documents
        ]
        reason = (
            "Schedule C net profit is unsafe to compute until deductible expenses are confirmed."
            if candidate_business_expenses == 0.0
            else f"Candidate receipts totaling ${candidate_business_expenses:,.2f} were found, but they are not applied automatically."
        )
        questions.append(
            build_question(
                "business-expenses",
                "What deductible business-expense total should be used for the 1099-NEC work, and should any candidate receipts be included?",
                "amount_with_confirmation",
                ["Schedule C lines 28 and 31", "self-employment profit review"],
                reason,
                35,
                evidence=candidate_evidence or None,
            )
        )

    if any(doc.get("doc_type") == "1099-B" and "capital_gains" not in doc.get("fields", {}) for doc in documents):
        questions.append(
            build_question(
                "capital-gains-summary",
                "What net capital gain or loss from your 1099-B support documents should the draft use?",
                "currency_amount",
                ["Form 1040 line 7"],
                "The repo supports 1099-B summary data, but it cannot invent a gain or loss number from a bare form notice.",
                45,
            )
        )

    for document in documents:
        doc_type = document.get("doc_type", "document")
        source_ref = document.get("source_ref", "unknown source")
        content_status = document.get("content_status")
        if content_status == "portal_notice_only":
            questions.append(
                build_question(
                    f"upload-{document.get('id', 'document')}",
                    f"Please upload the actual {doc_type} from {source_ref}.",
                    "file_upload",
                    ["document ingestion", "fact verification"],
                    "A portal notice is not enough to use the form contents in a return draft.",
                    15,
                    evidence=[source_ref],
                )
            )
        elif content_status == "unreadable_encrypted_attachment":
            questions.append(
                build_question(
                    f"unlock-{document.get('id', 'document')}",
                    f"Please upload or unlock the actual {doc_type} from {source_ref}.",
                    "file_upload",
                    ["document ingestion", "fact verification"],
                    "The attachment exists, but the deterministic flow could not read its contents.",
                    15,
                    evidence=[source_ref],
                )
            )
        elif content_status == "metadata_only":
            prompt = f"Please confirm the extracted {doc_type} details from {source_ref} against the actual form."
            if not document.get("fields"):
                prompt = f"Please upload the actual {doc_type} from {source_ref}; only metadata is available right now."
            questions.append(
                build_question(
                    f"confirm-{document.get('id', 'document')}",
                    prompt,
                    "confirmation_or_upload",
                    ["document provenance", "fact verification"],
                    "Metadata-only source hits are useful for discovery but not strong enough to treat as a final tax fact without confirmation.",
                    18,
                    evidence=[source_ref],
                )
            )

    if not documents and not any(connectors.values()):
        questions.append(
            build_question(
                "connect-or-upload",
                "Would you rather connect Gmail and Google Drive now, or upload your tax PDFs directly?",
                "single_choice",
                ["document discovery"],
                "The workflow is connector-first, but direct uploads are the safe fallback when no sources are connected.",
                5,
                options=["connect_gmail_and_drive", "upload_pdfs"],
            )
        )

    if unsupported_reasons:
        questions.append(
            build_question(
                "unsupported-handoff",
                "Do you want this repo to preserve the gathered facts for handoff, or should the unsupported items be removed from the draft package?",
                "single_choice",
                ["unsupported-case handling"],
                "Unsupported items should be surfaced explicitly instead of being silently folded into the draft.",
                90,
                blocking=False,
                options=["preserve_for_handoff", "remove_from_draft"],
                evidence=unsupported_reasons,
            )
        )

    known_reasons = {question["reason"] for question in questions}
    for item in missing_items:
        if item not in known_reasons and not item.startswith("Multiple work states are present."):
            questions.append(
                build_question(
                    f"follow-up-{len(questions) + 1}",
                    item,
                    "free_text",
                    ["review follow-up"],
                    item,
                    95,
                    blocking=False,
                )
            )

    questions.sort(key=lambda question: (question["priority"], question["id"]))
    return questions


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

    interview_questions = build_interview_questions(
        payload,
        tax_year=tax_year,
        illegal_reasons=illegal_reasons,
        unsupported_reasons=unsupported_reasons,
        missing_items=missing_items,
        resident_state=resident_state,
        work_states=work_states,
        nonemployee_compensation=nonemployee_compensation,
        business_expenses=business_expenses,
        candidate_business_expenses=candidate_business_expenses,
        candidate_expense_documents=candidate_expense_documents,
    )

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
        "interview_plan": {
            "summary": {
                "question_count": len(interview_questions),
                "blocking_count": sum(1 for question in interview_questions if question["blocking"]),
                "next_question_id": interview_questions[0]["id"] if interview_questions else None,
            },
            "questions": interview_questions,
        },
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
