/**
 * HTML Workbench DSH plugin — static host entry.
 *
 * Evaluates the canonical plugin body in `src/host.js` (the very same text
 * passed to `cordis_define` as `code.host`) and re-exports it for the Cordis
 * loader. The bundled Python service ships next to this package
 * (`scripts/workbench.py` + `assets/workbench.html`), so its absolute path is
 * resolved relative to THIS module (`import.meta.url`) — never hard-coded to a
 * specific machine — and handed to the shared body as `config.script`.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const scriptPath = resolve(here, '..', 'scripts', 'workbench.py')

// The body is a `return { ... }` statement; wrap it in a function and call it.
// eslint-disable-next-line no-new-func
const makePlugin = new Function(readFileSync(new URL('./host.js', import.meta.url), 'utf8'))
const plugin = makePlugin()

export const name = 'html-workbench'
export const inject = plugin.inject ?? []
// Inject the portably-resolved script path; a deployment-provided config may
// still override `script` / `editorRoot` / `port`.
export const apply = (ctx, config) => plugin.apply(ctx, { script: scriptPath, ...(config || {}) })
