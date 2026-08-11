import { chmod, cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontendRoot = path.join(projectRoot, 'service', 'public')
const sourceSkill = path.join(projectRoot, 'skill', 'open-html-editor')
const distRoot = path.join(projectRoot, 'dist')
const outputRoot = path.join(distRoot, 'skills', 'open-html-editor')
const outputScripts = path.join(outputRoot, 'scripts')
const outputAssets = path.join(outputRoot, 'assets')

function escapeInlineScript(source) {
  return source.replaceAll(/<\/script/gi, '<\\/script')
}

async function bundleFrontend() {
  const [template, workbenchCss, workbenchJs, grapesCss, grapesJs] = await Promise.all([
    readFile(path.join(frontendRoot, 'index.html'), 'utf8'),
    readFile(path.join(frontendRoot, 'workbench.css'), 'utf8'),
    readFile(path.join(frontendRoot, 'workbench.js'), 'utf8'),
    readFile(path.join(projectRoot, 'node_modules', 'grapesjs', 'dist', 'css', 'grapes.min.css'), 'utf8'),
    readFile(path.join(projectRoot, 'node_modules', 'grapesjs', 'dist', 'grapes.min.js'), 'utf8'),
  ])
  const shell = template
    .replace('<link rel="stylesheet" href="/vendor/grapesjs/css/grapes.min.css">', '<!-- GRAPES_CSS_BUNDLE -->')
    .replace('<link rel="stylesheet" href="/workbench.css">', '<!-- WORKBENCH_CSS_BUNDLE -->')
    .replace('<script src="/vendor/grapesjs/grapes.min.js"></script>', '<!-- GRAPES_JS_BUNDLE -->')
    .replace('<script type="module" src="/workbench.js"></script>', '<!-- WORKBENCH_JS_BUNDLE -->')
  const markers = ['GRAPES_CSS_BUNDLE', 'WORKBENCH_CSS_BUNDLE', 'GRAPES_JS_BUNDLE', 'WORKBENCH_JS_BUNDLE']
  if (!markers.every((marker) => shell.includes(`<!-- ${marker} -->`))) throw new Error('Frontend template is missing a bundle marker')
  return shell
    .replace('<!-- GRAPES_CSS_BUNDLE -->', () => `<style data-bundle="grapesjs">\n${grapesCss}\n</style>`)
    .replace('<!-- WORKBENCH_CSS_BUNDLE -->', () => `<style data-bundle="workbench">\n${workbenchCss}\n</style>`)
    .replace('<!-- GRAPES_JS_BUNDLE -->', () => `<script data-bundle="grapesjs">\n${escapeInlineScript(grapesJs)}\n</script>`)
    .replace('<!-- WORKBENCH_JS_BUNDLE -->', () => `<script type="module" data-bundle="workbench">\n${escapeInlineScript(workbenchJs)}\n</script>`)
}

async function main() {
  if (!outputRoot.startsWith(distRoot + path.sep)) throw new Error('Unsafe output directory')
  const html = await bundleFrontend()
  await rm(distRoot, { recursive: true, force: true })
  await mkdir(outputScripts, { recursive: true })
  await mkdir(outputAssets, { recursive: true })
  await cp(path.join(sourceSkill, 'SKILL.md'), path.join(outputRoot, 'SKILL.md'))
  await cp(path.join(sourceSkill, 'agents'), path.join(outputRoot, 'agents'), { recursive: true })
  await cp(path.join(projectRoot, 'service', 'server', 'workbench.py'), path.join(outputScripts, 'workbench.py'))
  await chmod(path.join(outputScripts, 'workbench.py'), 0o755)
  await writeFile(path.join(outputAssets, 'workbench.html'), html, 'utf8')
  process.stdout.write(`${JSON.stringify({ ok: true, output: outputRoot, bytes: Buffer.byteLength(html) })}\n`)
}

await main()
