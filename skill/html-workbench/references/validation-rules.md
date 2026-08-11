# HTML Workbench validation rules

Run the validator with Python 3.9 or newer:

```text
<python> <skill-dir>/scripts/validate_html.py <absolute-html-path>
```

It prints JSON and exits with `0` when no errors are present. Warnings and informational findings do not change the success exit code. An error exits with `1`.

## Errors

- `incomplete-document`: missing `html`, `head`, or `body`.
- `empty-workbench-id`: empty `data-wb-id`.
- `duplicate-workbench-id`: a stable Workbench ID is not unique.
- `duplicate-html-id`: a standard HTML ID is not unique, making interaction lookup ambiguous.
- `missing-interaction-target`: `data-target` cannot resolve to an `id` or `data-wb-id`.
- `dangerous-url`: an HTML URL attribute uses the `javascript:` scheme.
- `file-unreadable`: the file is missing, unreadable, or not UTF-8.

Fix all errors before opening the page in the workbench.

## Warnings

- `position-dependent-js-selector`: JavaScript contains `:nth-child()` or `:nth-of-type()`.
- `position-dependent-css-selector`: CSS contains a positional selector whose target may change after a drag.
- `structural-dom-traversal`: JavaScript relies on parents, siblings, or indexed children.
- `indexed-node-lookup`: JavaScript selects a fixed item from a node collection.
- `broad-dom-rewrite`: JavaScript replaces editable DOM through `innerHTML`, `outerHTML`, or `document.write`.
- `per-node-event-binding`: current nodes receive listeners individually instead of through delegation.
- `non-stable-interaction-target`: `data-target` contains a structural selector instead of a stable ID.

Treat warnings as review items. A warning can be acceptable when the affected subtree is deliberately static, but the Agent must explain that assumption instead of silently ignoring it.

## Informational findings

- `external-script-not-inspected`: an external script has no local source for static inspection. Verify its behavior in preview mode.

The scanner is intentionally heuristic. It does not parse the full JavaScript language, execute scripts, download remote code, or automatically rewrite the page.
