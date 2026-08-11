# Editable HTML generation guidelines

Read this reference before generating a page that will be opened in HTML Workbench, or when adapting an existing page whose JavaScript must survive visual rearrangement.

## Core contract

Generate position-independent interactions:

- Give interaction targets a stable `id` or `data-wb-id`.
- Connect triggers to targets with `data-action` and `data-target`.
- Resolve targets globally by stable identifier; do not rely on parent, sibling, child index, or visual order.
- Prefer one delegated event listener on `document` over listeners attached to every current node.
- Make initialization idempotent so preview reloads do not register duplicate listeners or duplicate DOM.
- Update narrow properties such as `textContent`, `hidden`, `classList`, ARIA attributes, and explicit state attributes. Avoid replacing editable containers through `innerHTML` or `outerHTML`.
- Keep application state in plain objects or explicit data attributes instead of long-lived references to editable DOM nodes.
- Use normal document flow, Flexbox, and Grid for movable layout. Positional selectors such as `:nth-child()` can silently change meaning after a drag.

## Recommended interaction pattern

```html
<button data-action="toggle" data-target="faq-answer-1">展开答案</button>
<div data-wb-id="faq-answer-1" hidden>答案内容</div>

<script>
document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-action="toggle"]')
  if (!trigger) return
  const target = document.querySelector(
    `[data-wb-id="${CSS.escape(trigger.dataset.target)}"]`
  )
  if (target) target.hidden = !target.hidden
})
</script>
```

The trigger and target may move independently without changing the lookup contract.

## Patterns to avoid

```js
document.querySelector('.cards > article:nth-child(2)')
button.parentElement.nextElementSibling
document.querySelectorAll('.tab')[2]
panel.innerHTML = renderEverything()
document.querySelectorAll('.button').forEach((node) => node.addEventListener('click', handler))
```

These patterns depend on the DOM snapshot that existed during initialization. Dragging, inserting, or recreating nodes can change their meaning or remove their listeners.

## Interaction verification

After generating the page:

1. Run `scripts/validate_html.py` and fix every error.
2. Review warnings and remove structural coupling when practical.
3. Open the page in HTML Workbench.
4. Move at least one interactive element in edit mode.
5. Switch to preview mode and exercise the affected interaction.
6. Save, reload, and repeat the interaction once more.

The validator is conservative and cannot prove arbitrary JavaScript safe. External scripts, framework-managed roots, Canvas/WebGL applications, and code generated at runtime require an actual preview test.
