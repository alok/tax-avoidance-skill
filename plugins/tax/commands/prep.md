---
name: prep
description: Build a prefilled federal return package for a simple U.S. individual return
user_invocable: true
---

# Tax Prep

Run the shared Tax Avoidance workflow for a normal person who wants to use Claude Cowork to do a simple U.S. federal return.

## Rules

- This means lawful tax avoidance, not tax evasion. Link users to [Tax avoidance](https://en.wikipedia.org/wiki/Tax_avoidance) and [Tax evasion](https://en.wikipedia.org/wiki/Tax_evasion) when clarifying the framing.
- Do not e-file.
- Do not pretend unsupported complexity is handled.
- If integrations only expose metadata and not the actual PDF or attachment content, ask for the file upload immediately.

## Workflow

1. Confirm the user is doing a simple 2025 federal individual return.
2. Check whether Gmail and Google Drive are connected.
3. Search for likely tax documents and build an inventory.
4. Ask only the missing questions required for a supported return.
5. Write an input JSON payload and run the shared deterministic flow:
   `uv run python .agents/skills/tax-avoidance/scripts/run_tax_flow.py --input <input.json> --out-dir <output-dir>`
6. Return:
   `tax-dossier.md`,
   `return-data.json`,
   `federal-lines.md`,
   and `missing-items.md`
7. Clearly separate:
   legal planning moves,
   unsupported complexity,
   illegal requests,
   and professional-review items.
