---
name: html-workbench
description: Start or reuse the bundled local HTML Workbench and return a visual editor URL for a local .html file. Use when the user asks to generate HTML and make it editable, convert an HTML page to an editable state, open a local HTML file in a visual editor, or continue AI and human editing against the same source file.
---

# HTML Workbench

Open a complete local HTML document in the bundled GrapesJS workbench. Keep the source file as the shared source of truth for visual edits and later AI edits.

## Workflow

1. Resolve the target `.html` file to an absolute path. If the user also asked to generate the page, create and verify a complete document containing `html`, `head`, and `body` before continuing.
2. Resolve the directory containing this `SKILL.md`. Treat its `scripts/workbench.py` as the service entrypoint.
3. Find Python 3 in this order:
   - Run `python3 --version`.
   - Run `python --version` if `python3` is unavailable.
   - On Windows, run `py -3 --version` if both commands are unavailable.
4. Require Python 3.9 or newer. If no compatible interpreter exists, explain that the workbench needs Python 3.9+ and ask for confirmation before installing software. After confirmation, use the platform's normal trusted installer or package manager, then repeat the version check.
5. Run the entrypoint with the selected interpreter:

```text
<python> <skill-dir>/scripts/workbench.py open <absolute-html-path>
```

6. On the first run, allow the service to download the pinned GrapesJS assets. It verifies their SHA-256 hashes and caches them locally; later runs do not require network access. Do not download or inject an unverified substitute yourself.
7. Read the JSON written to stdout. When `ok` is true, return `url` as a clickable link. Mention whether the existing service was reused only when that detail helps diagnose behavior.
8. If startup fails, report the returned error and inspect the log path when one is provided. For `VENDOR_DOWNLOAD_FAILED`, explain that all configured sources were unreachable and ask the user to check the network before retrying. Do not replace the service with an ad-hoc server.

## Service commands

Run the service independently in the foreground:

```text
<python> <skill-dir>/scripts/workbench.py serve
```

Check an existing service:

```text
<python> <skill-dir>/scripts/workbench.py health
```

Use `--port` only to avoid a confirmed port collision. Use `--editor-root` only when the target file is outside the current user's home directory and the user placed that location in scope.

## Safety and file behavior

- Bind only to `127.0.0.1`; never expose the editor on a public interface.
- Treat the specified HTML file as the source of truth. The workbench writes visual edits back to it.
- Preserve external file changes with revision checks; never force an overwrite after a conflict.
- Do not install Python or another runtime without explicit user confirmation.
- Keep third-party assets pinned and hash-verified. The service tries a China-friendly npm mirror first and falls back to three public CDNs.
- Return the URL instead of claiming the browser is editable before the health check and document load succeed.
