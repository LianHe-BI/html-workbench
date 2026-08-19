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
import { tmpdir } from 'node:os'
import { dirname, resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const scriptPath = resolve(here, '..', 'scripts', 'workbench.py')
// Runtime state must be writable from DSH's workspace-write sandbox. `tmpdir()`
// is platform-aware: /tmp on macOS/Linux, %TEMP% on Windows. The content is only
// logs and a re-downloadable GrapesJS cache, so it is deliberately ephemeral.
const runtimeDir = join(tmpdir(), 'html-workbench-dsh')

// The body is a `return { ... }` statement; wrap it in a function and call it.
// eslint-disable-next-line no-new-func
const makePlugin = new Function(readFileSync(new URL('./host.js', import.meta.url), 'utf8'))
const plugin = makePlugin()

export const name = 'html-workbench'
export const inject = plugin.inject ?? []
// Inject paths resolved by Node rather than assuming POSIX separators. A
// deployment-provided config may still override every value.
export const apply = (ctx, config) => plugin.apply(ctx, {
  script: scriptPath,
  runtimeDir,
  ...(config || {}),
})
