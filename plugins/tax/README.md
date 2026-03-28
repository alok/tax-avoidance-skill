# Tax Plugin

`/tax:prep` is the primary Claude Cowork entrypoint for this repository.

This plugin shares the same workflow and legality framing as the canonical Codex skill:

- legal tax avoidance only
- not tax evasion
- simple U.S. federal individual returns only
- connector-first discovery, explicit upload fallback for real PDFs
- safe household and dependent scaffolding without storing full SSNs in the artifact payload
- prefilled federal return package, not e-filing

If Gmail or Google Drive integrations cannot provide the actual attachment content, stop and ask the user to upload the PDF instead of pretending the content was ingested.
