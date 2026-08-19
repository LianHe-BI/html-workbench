/**
 * Regression contracts for the editor-side visual-context affordance.
 *
 * The workbench frontend is bundled as a browser module, so these assertions
 * intentionally inspect its source-level contract rather than importing it in
 * Node (which would require GrapesJS and a full DOM). They pin the two product
 * guarantees that previously regressed in production:
 *
 * 1. “Add to chat” is read-only — a click must not mint an id or save the page.
 * 2. Its toolbar affordance communicates “add this to conversation”, rather
 *    than masquerading as GrapesJS’s existing move-up command.
 */

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(HERE, '..', 'service', 'public', 'workbench.js'), 'utf8')

const functionBody = (name, nextMarker) => {
  const start = source.indexOf(`async function ${name}`)
  assert.notEqual(start, -1, `${name} must exist`)
  const end = source.indexOf(nextMarker, start)
  assert.notEqual(end, -1, `${name} must end before ${nextMarker}`)
  return source.slice(start, end)
}

test('add-to-chat context flow never writes or promotes an identity', () => {
  const body = functionBody('sendSelectionToChat', '// The workbench runs inside an iframe')

  // A visual selection is context, not an edit. The previous implementation
  // called both `save()` and `/api/anchor`, causing a harmless click to fail for
  // valid file:// documents outside DSH’s writable workspace.
  assert.doesNotMatch(body, /\bawait save\s*\(/)
  assert.doesNotMatch(body, /\/api\/anchor/)
  assert.doesNotMatch(body, /promote_identities/)
  assert.match(body, /\/api\/context/)
  assert.match(body, /publishContext\(packet\)/)
})

test('the context toolbar button names the user action accessibly', () => {
  const start = source.indexOf('function addContextToolbarItem')
  const end = source.indexOf('function updateAttributePanel', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const body = source.slice(start, end)

  assert.match(body, /title: '添加到对话上下文'/)
  assert.match(body, /aria-label': '将选中元素添加到对话上下文'/)
  assert.match(body, /command: CONTEXT_TOOLBAR_COMMAND/)
})

test('the context toolbar icon is a chat bubble with an add mark', () => {
  const start = source.indexOf('function addContextToolbarItem')
  const end = source.indexOf('function updateAttributePanel', start)
  const body = source.slice(start, end)

  // Bubble outline plus a vertical and horizontal stroke (the +). Avoid a
  // brittle full-SVG snapshot while pinning the visual grammar at 15px size.
  assert.match(body, /width:15px;height:15px/)
  assert.match(body, /M20 11\.3/)
  assert.match(body, /M15\.8 7\.4v4\.2/)
  assert.match(body, /M13\.7 9\.5h4\.2/)
  assert.doesNotMatch(body, /m5 12 7-7 7 7/)
})
