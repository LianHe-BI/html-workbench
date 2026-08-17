/**
 * HTML Workbench DSH plugin — Host half (function body).
 *
 * This file is the plain-JavaScript function body consumed by DeepSeek
 * Harness's dynamic Cordis plugin loader: pass this exact text as `code.host`
 * to `cordis_define`. The static host entry `src/index.js` evaluates this same
 * body via `new Function` and re-exports it, so it runs unchanged in both
 * modes. `harness` usage is guarded (`typeof harness !== 'undefined'`) so the
 * body also runs as a static bundle where that symbol does not exist.
 *
 * Responsibilities (runs in the DSH Node.js process):
 *  - Start / reuse the local `html-workbench` Python service on registration
 *    and stop the process it started when the plugin unloads (side-effect
 *    lifecycle via ctx.effect).
 *  - Track HTML files produced by the `write` / `edit` tools via `tools/result`.
 *  - Expose the same three operations through two transports:
 *      * dynamic: `harness.handle` Package-private RPC (Client `host.call`);
 *      * static:  `webServer.register` HTTP routes under `/html-workbench/*`.
 */

return {
  inject: ['shell', 'timer', 'webServer'],
  apply(ctx, config) {
    // 静态/NPM 装载时由 src/index.js 相对插件自身解析 scripts/workbench.py 并注入 config.script；
    // 动态装载（cordis_define）无 config → script 为空，服务不自动拉起（仅注册传输层）。
    // editorRoot 可选：缺省不传 --editor-root，由 workbench.py 自行回退到用户家目录。
    const opts = config || {}
    const PORT = opts.port || 4317
    const SCRIPT = opts.script || null
    const EDITOR_ROOT = opts.editorRoot || null

    let assets = []
    let seq = 0
    let ownedProcess = null
    let serviceRunning = false
    let startError = null
    let disposed = false

    const shell = ctx.get('shell')

    const runCli = async (args, timeoutMs) => {
      if (!shell || !SCRIPT) return null
      try {
        const spec = shell.resolve({
          command: 'python3 "' + SCRIPT + '" ' + args,
          timeoutMs: timeoutMs || 15000,
          stdoutMaxBytes: 64 * 1024,
        })
        return await shell.run(spec)
      } catch (e) {
        return null
      }
    }

    const health = async () => {
      const r = await runCli('health --port ' + PORT, 8000)
      if (!r || r.exitCode !== 0) return null
      try {
        const p = JSON.parse((r.stdout && r.stdout.text) || '')
        return p && p.ok === true ? p : null
      } catch (e) {
        return null
      }
    }

    const startService = async () => {
      if (disposed) return null
      if (serviceRunning) return health()
      const existing = await health()
      if (existing) { serviceRunning = true; startError = null; return existing }
      if (!shell) { startError = 'shell service unavailable'; return null }
      if (!SCRIPT) { startError = 'workbench.py 路径未配置（请用静态装载并随包分发 scripts/workbench.py）'; return null }
      let proc = null
      try {
        const editorRootArg = EDITOR_ROOT ? ' --editor-root "' + EDITOR_ROOT + '"' : ''
        const spec = shell.resolve({
          command: 'python3 "' + SCRIPT + '" serve --port ' + PORT + editorRootArg,
          stdoutMaxBytes: 64 * 1024,
        })
        proc = shell.start(spec)
        if (disposed) { try { proc.kill() } catch (e) {} return null }
        ownedProcess = proc
        for (let i = 0; i < 240; i += 1) {
          const h = await health()
          if (h) { serviceRunning = true; startError = null; return h }
          await ctx.timeout(250)
        }
        startError = 'service did not become healthy'
        return null
      } catch (e) {
        startError = e && e.message ? String(e.message) : String(e)
        if (proc) { try { proc.kill() } catch (e2) {} }
        ownedProcess = null
        return null
      }
    }

    // 生命周期副作用：卸载时停掉本插件自己启动的服务进程。
    ctx.effect(() => () => {
      disposed = true
      const proc = ownedProcess
      ownedProcess = null
      serviceRunning = false
      if (proc) { try { proc.kill() } catch (e) { console.error('[html-workbench] stop failed', e) } }
    })

    const recordAsset = (path, kind) => {
      const existing = assets.find((a) => a.path === path)
      if (existing) {
        existing.kind = kind
        existing.at = Date.now()
        existing.seq = ++seq
      } else {
        assets.push({ id: 'w' + (++seq), path: path, kind: kind, at: Date.now(), seq: seq })
        if (assets.length > 500) assets = assets.slice(-500)
      }
    }

    ctx.on('tools/result', (exec, result) => {
      try {
        if (!exec || !result || result.isError === true) return
        if (exec.name !== 'write' && exec.name !== 'edit') return
        const args = exec.arguments || {}
        const path = args.file_path
        if (typeof path !== 'string' || !path) return
        if (!/\.html?$/i.test(path)) return
        recordAsset(path, exec.name === 'write' ? 'create' : 'edit')
      } catch (e) {
        console.error('[html-workbench] track failed', e)
      }
    })

    const snapshot = () => assets.slice().sort((a, b) => b.seq - a.seq)

    const openFile = async (file) => {
      if (typeof file !== 'string' || !file) return { ok: false, error: 'file is required' }
      if (!/\.html?$/i.test(file)) return { ok: false, error: 'only .html files are supported' }
      if (!SCRIPT) return { ok: false, error: startError || 'workbench.py 路径未配置' }
      const wasUp = await health()
      if (!wasUp) await startService()
      const h = await health()
      if (!h) return { ok: false, error: startError || 'workbench service unavailable' }
      return {
        ok: true,
        url: 'http://127.0.0.1:' + PORT + '/?file=' + encodeURIComponent(file),
        reused: !!wasUp,
        port: PORT,
      }
    }

    const resolvePath = async (file) => {
      if (typeof file !== 'string') return { ok: false, error: 'file is required' }
      const trimmed = file.trim()
      if (!trimmed) return { ok: true, empty: true, isHtml: false, exists: false }
      if (!/\.html?$/i.test(trimmed)) return { ok: true, isHtml: false, exists: false }
      if (!shell) return { ok: true, isHtml: true, exists: null }
      const arg = JSON.stringify(trimmed)
      const spec = shell.resolve({ command: 'python3 -c "import os,sys; sys.exit(0 if os.path.isfile(sys.argv[1]) else 1)" ' + arg, timeoutMs: 5000, stdoutMaxBytes: 1024 })
      try {
        const r = await shell.run(spec)
        return { ok: true, isHtml: true, exists: !!(r && r.exitCode === 0) }
      } catch (e) {
        return { ok: true, isHtml: true, exists: null }
      }
    }

    // 动态传输：Package-private RPC（仅动态运行时存在 harness）。
    if (typeof harness !== 'undefined') {
      harness.handle('list', () => ({ ok: true, running: serviceRunning, owned: !!ownedProcess, port: PORT, assets: snapshot() }))
      harness.handle('status', async () => { const h = await health(); return { ok: !!h, running: !!h, owned: !!ownedProcess, port: PORT, info: h || null } })
      harness.handle('open', async (args) => openFile(args && args.file))
      harness.handle('resolve', async (args) => resolvePath(args && args.file))
    }

    // 静态传输：HTTP 路由，供静态 client bundle（fetch）与直接浏览器访问使用。
    const webServer = ctx.get('webServer')
    if (webServer) {
      const sendJson = (res, status, body) => {
        res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify(body))
      }
      const parseQuery = (req) => {
        const qs = (req.url || '').split('?')[1] || ''
        const out = {}
        qs.split('&').forEach((pair) => {
          if (!pair) return
          const eq = pair.indexOf('=')
          const k = decodeURIComponent(eq < 0 ? pair : pair.slice(0, eq))
          const v = decodeURIComponent(eq < 0 ? '' : pair.slice(eq + 1))
          out[k] = v
        })
        return out
      }
      ctx.effect(() => webServer.register({
        kind: 'exact',
        path: '/html-workbench/list',
        handler: (req, res) => sendJson(res, 200, { ok: true, running: serviceRunning, owned: !!ownedProcess, port: PORT, assets: snapshot() }),
      }), 'html-workbench: list route')
      ctx.effect(() => webServer.register({
        kind: 'exact',
        path: '/html-workbench/status',
        handler: async (req, res) => { const h = await health(); sendJson(res, 200, { ok: !!h, running: !!h, owned: !!ownedProcess, port: PORT, info: h || null }) },
      }), 'html-workbench: status route')
      ctx.effect(() => webServer.register({
        kind: 'exact',
        path: '/html-workbench/open',
        handler: async (req, res) => {
          const file = parseQuery(req).file
          const out = await openFile(file)
          sendJson(res, out.ok ? 200 : 400, out)
        },
      }), 'html-workbench: open route')
      ctx.effect(() => webServer.register({
        kind: 'exact',
        path: '/html-workbench/resolve',
        handler: async (req, res) => {
          const out = await resolvePath(parseQuery(req).file)
          sendJson(res, out.ok ? 200 : 400, out)
        },
      }), 'html-workbench: resolve route')
    }

    // 注册时主动拉起服务（异步，不阻塞 apply）。
    void startService()
  },
}
