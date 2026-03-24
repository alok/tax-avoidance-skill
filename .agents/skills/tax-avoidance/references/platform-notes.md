# Platform Notes

## Codex

Codex is the preferred path for this project because the Codex app and its connectors are better suited to document-heavy workflows. Skills are documented at [OpenAI Codex Agent Skills](https://developers.openai.com/codex/skills/), and connector availability is documented in the [OpenAI connectors guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp/).

## Claude Cowork

Claude Cowork is supported as a secondary path via a plugin wrapper. Use its integrations for discovery and interview convenience, but be explicit when the user needs to upload actual PDFs. Relevant docs:

- [Claude integrations setup](https://support.claude.com/en/articles/10168395-set-up-claude-integrations)
- [Use Google Workspace connectors in Claude](https://support.claude.com/id/articles/10166901-gunakan-konektor-google-workspace)
- [Use plugins in Cowork](https://support.claude.com/en/articles/13837440-use-plugins-in-cowork)

## Shared Rule

Do not promise a magic ingestion path. If the platform cannot expose the underlying tax form content, ask for the PDF immediately.

