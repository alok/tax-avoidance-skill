# Tax Avoidance

**Legal tax avoidance only. Not tax evasion.** The project uses the phrase "tax avoidance" in the ordinary legal sense of lawful tax minimization, not illegal concealment or fraud. See [Tax avoidance](https://en.wikipedia.org/wiki/Tax_avoidance) and [Tax evasion](https://en.wikipedia.org/wiki/Tax_evasion).

Tax Avoidance is a normie-focused tax copilot for the Codex app and Claude Cowork. It is built to help a normal person gather tax documents, answer only the necessary interview questions, and assemble a prefilled federal return package for a **simple 2025 U.S. federal individual return** without e-filing.

## What A Normal Codex App User Needs

The intended user is someone with the standard Codex app experience plus ordinary personal accounts and files:

- the Codex app itself
- Gmail connected if their tax forms arrive by email
- Google Drive connected if they store PDFs or Google Docs there
- the ability to upload PDFs when a connector only exposes metadata or a portal notice

No separate backend or custom API setup is required for the main workflow in this repository.

## What It Does

- Uses existing desktop AI UIs instead of building a separate product.
- Optimizes for Codex first, because Codex has a stronger connector and document-ingestion story for Gmail, Google Drive, Dropbox, and related tools. See the [OpenAI connectors guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp/).
- Keeps a Claude Cowork path with the same interview flow, but expects explicit PDF upload when Gmail or Drive integrations cannot expose the actual attachment content. See [Claude integrations setup](https://support.claude.com/en/articles/10168395-set-up-claude-integrations), [Use Google Workspace connectors in Claude](https://support.claude.com/id/articles/10166901-gunakan-konektor-google-workspace), and [Use plugins in Cowork](https://support.claude.com/en/articles/13837440-use-plugins-in-cowork).
- Produces the same artifact set every time:
  - `tax-dossier.md`
  - `return-data.json`
  - `federal-lines.md`
  - `missing-items.md`
- Surfaces likely SaaS or tooling receipts as **candidate business expenses** without silently applying them to Schedule C.
- Totals candidate expenses using the receipt or payment date for the target tax year, while still showing out-of-year receipts in the document inventory for auditability.
- Captures resident-state and work-state context now, even before automated state calculations are implemented.
- Preserves safe dependent and household context so a future child-credit or dependent-care review stays visible without storing full SSNs or pretending eligibility is resolved.

## Scope

This repository targets **simple federal individual returns** only: single or married-filing-jointly households with wage, contractor, and investment income plus common deductions and credits. It supports a simple Schedule C skeleton for contractor `1099-NEC` work when gross receipts are known and business expenses can be gathered. It still excludes rental income, K-1s, stock options, QSBS, trusts, estates, multistate returns, and international filings.

All substantive tax facts should trace back to primary IRS sources such as [Publication 17](https://www.irs.gov/publications/p17), [Publication 505](https://www.irs.gov/publications/p505), [Publication 590-A](https://www.irs.gov/publications/p590a), and [Publication 969](https://www.irs.gov/forms-pubs/about-publication-969). Wikipedia is only used for the avoidance-vs-evasion terminology framing.

## Install In Codex

Codex reads repository-scoped skills from `.agents/skills`, so this repo is directly usable after cloning:

```bash
git clone https://github.com/alok/tax-avoidance-skill.git
cd tax-avoidance-skill
```

Then invoke the skill explicitly:

```text
$tax-avoidance
```

Recommended starting prompt:

```text
Use $tax-avoidance to connect Gmail and Google Drive, gather my 2025 tax documents, ask only the missing questions, and assemble a prefilled federal return package.
```

If the user is a contractor or freelancer, a stronger version is:

```text
Use $tax-avoidance to gather my 2025 W-2s, 1099s, and tax receipts, build a Schedule C skeleton if I have 1099-NEC income, and tell me exactly what is still missing.
```

## Try It Locally Without Connectors

If you want to sanity-check the deterministic layer before using your own data:

```bash
uv run python .agents/skills/tax-avoidance/scripts/run_tax_flow.py \
  --input examples/contractor-and-investment-input.json \
  --out-dir output/example-run
```

That should create the same four standard artifacts in `output/example-run/`.

The example input now includes a safe public `household.dependents` block. Use booleans like `tin_available` instead of placing a real SSN or ITIN in the artifact inputs.

## Install In Claude Cowork

This repo also ships a Cowork plugin wrapper:

```bash
/plugin marketplace add alok/tax-avoidance-skill
/plugin install tax
```

Primary command:

```bash
/tax:prep
```

## Workflow

1. Check whether Gmail and Google Drive are available. If they are missing, ask the user to connect them immediately or upload PDFs.
2. Search for likely tax documents using fixed, opinionated queries instead of asking the user to browse manually.
3. Capture resident-state and work-state context as early as possible.
4. Build a document inventory and ask the minimum remaining interview questions.
5. Normalize extracted facts plus safe household scaffolding into `return-data.json`.
6. Assemble a prefilled federal line map and a human-readable dossier.
7. Surface likely business-expense receipts separately from confirmed deductible expenses.
8. Clearly label legal planning moves, missing items, unsupported complexity, state follow-up, and anything that needs professional review.

## Repository Layout

- `.agents/skills/tax-avoidance/` holds the canonical Codex skill, references, and deterministic scripts.
- `plugins/tax/` wraps the same workflow for Claude Cowork.
- `tests/` validates happy paths, connector fallbacks, illegal-request refusals, and artifact consistency.

## Notes

- This project does **not** e-file.
- This project does **not** give personalized legal advice.
- This project does **not** store full SSNs or ITINs in its public-safe example and artifact scaffolding.
- Illegal requests such as hiding income, concealing ownership, or skipping required reporting must be refused and redirected to lawful compliance.
- If a portal notice exists but the actual form does not, the workflow should stop and ask for the downloadable PDF or the line-item figures.
