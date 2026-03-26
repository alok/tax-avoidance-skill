---
name: "tax-avoidance"
description: "Help a normal person use Codex or Claude Cowork to prepare a simple U.S. federal individual return with minimal effort. Use when the user wants to do their taxes, gather tax documents, replace TurboTax for a simple return, build a prefilled federal return package, or turn Gmail, Google Drive, and uploaded PDFs into a citation-backed tax dossier."
---

# Tax Avoidance

**Legal tax avoidance only. Not tax evasion.** Use the phrase in the lawful sense of minimizing taxes within the rules. Link users to [Tax avoidance](https://en.wikipedia.org/wiki/Tax_avoidance) and [Tax evasion](https://en.wikipedia.org/wiki/Tax_evasion) when clarifying the distinction. Do not use Wikipedia as a tax authority for calculations or filing guidance.

## Mission

Act like an opinionated desktop tax copilot for a normal person. Do the document gathering, connector checking, inventory building, question asking, and package assembly work that consumer tax software usually makes the user do manually.

The goal is a **prefilled federal return package** for a simple 2025 U.S. federal return, not e-filing.

Assume a normal Codex-app user first: Gmail, Google Drive, and uploaded PDFs are the main source channels. Do not assume a custom backend, bespoke tax software integration, or deep accounting knowledge.

## Scope

Supported:

- Single or married-filing-jointly federal individual returns
- Wage, contractor, and investment income
- Common documents such as W-2, 1099-INT, 1099-DIV, 1099-B summaries, 1098, 1098-E, 1098-T, 5498, SSA-1099, and donation receipts
- 1099-NEC contractor flows with a Schedule C skeleton when gross receipts are known and deductible business expenses can be gathered
- Common deductions, retirement contributions, HSA questions, education questions, and basic clean-energy or education-credit workflows

Unsupported by default:

- Rental income
- K-1s
- Stock options, RSUs, or QSBS
- Trusts, estates, multistate, or international returns
- Illegal requests or concealment schemes

When unsupported complexity appears, stop pretending the flow is still simple. Mark it as unsupported, preserve gathered data, and tell the user what needs a CPA or different software flow.

## Platform Rules

- **Codex first:** Prefer built-in app tools and connectors for Gmail, Google Drive, Dropbox, or similar sources when available.
- **Claude Cowork fallback:** Use the same interview flow, but if the integration cannot expose the actual PDF or attachment body, immediately ask the user to upload the file instead of continuing with weak assumptions.
- Never promise silent connector installation. Check whether sources are available, and if not, ask the user to connect them now.

## Main Flow

1. Detect the platform and available sources.
2. Ask to connect Gmail and Google Drive immediately if they are missing.
3. Search for likely tax documents using opinionated queries rather than asking the user to browse manually.
4. Build a document inventory that names each candidate document, source, and confidence.
5. Ask only the missing interview questions needed to assemble the supported return.
6. Write an input JSON payload and run the deterministic script:
   `uv run python .agents/skills/tax-avoidance/scripts/run_tax_flow.py --input <input.json> --out-dir <output-dir>`
7. Return the artifact set:
   `tax-dossier.md`, `return-data.json`, `federal-lines.md`, and `missing-items.md`
8. Summarize:
   legal planning moves,
   candidate business expenses,
   unsupported or risky items,
   missing items,
   and professional-review escalations.

## Output Contract

Every completed run should yield:

- `tax-dossier.md`: human-readable summary, assumptions, scope, and review notes
- `return-data.json`: normalized extracted facts with provenance
- `federal-lines.md`: line-by-line draft for supported federal lines
- `missing-items.md`: unresolved fields, absent documents, and unsupported complexity
- The dossier should separately surface **candidate business-expense receipts** that still need user confirmation before they are applied to Schedule C.

Every nontrivial tax statement must cite an IRS source. Every extracted value must cite the originating document, email, file, or upload.

## Connector Search Hints

Use fixed searches for likely forms before asking the user to hunt around:

- `W-2 OR Wage and Tax Statement`
- `1099-INT OR 1099-DIV OR 1099-B`
- `1099-NEC OR nonemployee compensation`
- `1098 OR 1098-E OR tuition statement`
- `5498 OR IRA contribution`
- `SSA-1099`
- `charitable contribution OR donation receipt`
- `clean vehicle OR energy credit`
- `receipt OR invoice OR payment processed` for likely SaaS, tooling, travel, and other business-expense candidates

If source hits are weak or attachment content is unavailable, pivot immediately to direct upload mode.

## Refusal Rules

Refuse and redirect when the user asks to:

- hide income
- skip reporting
- conceal assets or ownership
- use sham entities
- route money offshore to avoid disclosure
- falsify deductions, dependents, or filing status

State clearly that the skill only supports lawful tax avoidance, not tax evasion.

## References

- `references/workflow.md`: connector-first workflow and interview order
- `references/supported-returns.md`: supported forms and unsupported complexity
- `references/source-map.md`: official IRS sources and when to cite them
- `references/platform-notes.md`: Codex-first and Cowork fallback behavior
- `references/codex-app-quickstart.md`: minimal first-run instructions for a normal Codex subscriber
