# Workflow

## Goal

Get from messy user documents to a prefilled federal return package with the fewest possible questions.

## Codex App First-Run

For a plain Codex app user:

1. Ask for Gmail and Google Drive connection up front.
2. If a source only exposes a portal notice, ask for the actual PDF immediately.
3. Prefer uploaded PDFs over vague email snippets.
4. Treat likely SaaS or tooling receipts as candidate expenses until the user confirms they belong on Schedule C.

## Order Of Operations

1. Confirm this is a simple 2025 federal individual return.
2. Check Gmail and Google Drive access.
3. Search for likely forms before asking the user to browse.
4. Build a document inventory with source, doc type, and confidence.
5. Ask only the missing questions needed for supported lines.
6. Normalize everything into structured facts.
7. Assemble the artifact set.
8. Flag unsupported complexity and illegal requests explicitly.

## Connector Priority

- Codex path: Gmail, Google Drive, Dropbox, then uploads
- Claude Cowork path: Gmail and Google Drive for discovery, then uploads for actual PDFs when needed

## Expense Discovery

- Search for obvious receipts and invoices after document discovery, not before.
- Prefer vendors that look plausibly work-related: AI model providers, developer tooling, conferencing, hosting, and issue-tracking tools.
- Do not silently convert every receipt into a deduction. Surface them as candidate expenses with totals and source links, then ask the user to confirm inclusion.
- Use the receipt or payment date to decide whether a candidate expense belongs in the target tax year.
- Keep out-of-year receipts visible in the inventory, but do not include them in the candidate-expense total for the return year.

## Social Security Review

- When an `SSA-1099` is present, preserve the gross benefits on Form 1040 line `6a`.
- Only place an amount on line `6b` after the taxable Social Security figure has been confirmed.
- Until that taxable figure is confirmed, keep the return in review mode and add a missing-item prompt instead of folding gross benefits into total income.

## Interview Principles

- Ask for filing status only after document collection begins.
- Ask one question at a time when the answer changes supported-line output.
- Prefer targeted clarifications over generic tax questionnaires.
- If the user obviously falls outside the supported scope, stop early and preserve gathered data for handoff.
- If a contractor flow exists, ask about business expenses before trying to compute net profit.
