/**
 * HTML Workbench DSH plugin — Client half (function body).
 *
 * This file is the plain-JavaScript function body consumed by DeepSeek
 * Harness's dynamic Cordis plugin loader: pass this exact text as `code.client`
 * to `cordis_define`. The static client bundle wraps this same body in
 * `window.__ModuleLoader__.load(...)` at build time.
 *
 * Responsibilities (runs in the browser):
 *  - Register a right-side panel + corner trigger in `shell.overlay`.
 *  - Preview takes the full panel height; the HTML-asset picker is a compact,
 *    collapsible dock at the bottom (a <select> switcher + expandable list).
 *  - Open a file by calling Host `open`, then embed the workbench URL in an
 *    iframe. Left edge is draggable to resize the panel width.
 */

return {
  inject: ['timer'],
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return

    styles.insert(`
html #root { margin-right: var(--hwb-panel-width, 0px); transition: margin-right var(--ds-transition-duration-slow, 200ms) ease; }
body[data-hwb-dragging] #root { transition: none; }
body[data-hwb-dragging] { user-select: none; }
.hwb-panel, .hwb-panel * { box-sizing: border-box; }
.hwb-panel { position: fixed; top: 0; right: 0; bottom: 0; width: 820px; max-width: calc(100vw - 24px); display: flex; flex-direction: column; background: var(--dsw-alias-bg-base); color: var(--dsw-alias-label-primary); border-left: 1px solid var(--dsw-alias-border-l1); box-shadow: var(--dsw-shadow-lv2); z-index: 9999; font-family: var(--dsw-font-family, system-ui, sans-serif); font-size: 13px; line-height: 1.5; pointer-events: auto; }
.hwb-resize { position: absolute; left: -4px; top: 0; bottom: 0; width: 9px; cursor: col-resize; z-index: 3; touch-action: none; }
.hwb-resize::after { content: ""; position: absolute; left: 4px; top: 0; bottom: 0; width: 2px; background: transparent; transition: background .15s; }
.hwb-resize:hover::after, .hwb-resize:active::after { background: var(--dsw-alias-interactive-bg-hover-accent); }
.hwb-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); flex: none; }
.hwb-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dsw-alias-state-error-primary); flex: none; }
.hwb-dot.on { background: var(--dsw-alias-state-success-primary); }
.hwb-titlewrap { min-width: 0; display: flex; flex-direction: column; }
.hwb-title { font-weight: 600; font-size: 13px; line-height: 1.2; white-space: nowrap; }
.hwb-sub { font-size: 11px; color: var(--dsw-alias-label-tertiary); line-height: 1.2; }
.hwb-spacer { flex: 1; }
.hwb-close { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border: none; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; border-radius: 6px; flex: none; }
.hwb-close:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-interactive-bg-hover); }
.hwb-preview { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; background: #fff; }
.hwb-frame { flex: 1; border: 0; width: 100%; }
.hwb-hint { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--dsw-alias-label-tertiary); text-align: center; padding: 16px; }
.hwb-error { padding: 10px 14px; color: var(--dsw-alias-state-error-primary); font-size: 12px; }
.hwb-dock { flex: none; border-top: 1px solid var(--dsw-alias-border-l1); background: var(--dsw-alias-bg-layer-1); display: flex; flex-direction: column; }
.hwb-dockbar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; }
.hwb-select { flex: 1; min-width: 0; height: 28px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: var(--dsw-alias-bg-base); color: var(--dsw-alias-label-primary); font: inherit; font-size: 12px; padding: 0 8px; cursor: pointer; }
.hwb-count { font-size: 11px; color: var(--dsw-alias-label-tertiary); flex: none; white-space: nowrap; }
.hwb-docktoggle { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border: none; background: transparent; color: var(--dsw-alias-label-secondary); cursor: pointer; border-radius: 6px; flex: none; }
.hwb-docktoggle:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-interactive-bg-hover); }
.hwb-docklist { flex: none; max-height: 38vh; overflow-y: auto; border-top: 1px solid var(--dsw-alias-border-l2); }
.hwb-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--dsw-alias-border-l2); cursor: pointer; }
.hwb-item:hover { background: var(--dsw-alias-interactive-bg-hover); }
.hwb-item.active { background: var(--dsw-alias-interactive-bg-active); }
.hwb-item-main { flex: 1; min-width: 0; }
.hwb-item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.hwb-item-path { font-size: 11px; color: var(--dsw-alias-label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.hwb-item-btn { border: 1px solid var(--dsw-alias-border-l2); background: transparent; color: var(--dsw-alias-label-secondary); border-radius: 6px; padding: 2px 9px; cursor: pointer; font-size: 12px; flex: none; }
.hwb-item-btn:hover { background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.hwb-dockempty { padding: 14px; color: var(--dsw-alias-label-tertiary); text-align: center; font-size: 12px; }
/* Keep the trigger below the DSH session header's title row (~44px tall: 12px
   padding + 32px min-height) so it never covers the right-aligned header
   utilities — e.g. the "Session Log" button — when a session is open. */
.hwb-trigger { position: fixed; top: 56px; right: 12px; z-index: 10000; width: 36px; height: 36px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; pointer-events: auto; }
.hwb-trigger:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-interactive-bg-hover); }
`)

    const DEFAULT_WIDTH = 820
    const MIN_WIDTH = 480

    const store = {
      open: false,
      panelWidth: DEFAULT_WIDTH,
      expanded: false,
      assets: [],
      running: false,
      current: null,
      loading: false,
      error: null,
      listeners: [],
      subscribe(fn) { this.listeners.push(fn); return () => { this.listeners = this.listeners.filter((f) => f !== fn) } },
      set(p) { Object.assign(this, p); this.listeners.forEach((fn) => { try { fn() } catch (e) {} }) },
    }

    const useStore = () => {
      const [, force] = React.useState(0)
      React.useEffect(() => store.subscribe(() => force((x) => x + 1)), [])
      return store
    }

    const basename = (p) => {
      const parts = String(p).split('/')
      return parts[parts.length - 1] || p
    }

    const refresh = () => {
      host.call('list').then((res) => {
        if (res && res.ok) store.set({ assets: res.assets || [], running: !!res.running })
        else store.set({ error: (res && res.error) || 'list failed' })
      }).catch((e) => store.set({ error: String(e && e.message ? e.message : e) }))
    }

    const openFile = (path) => {
      store.set({ loading: true, current: { path: path, url: null }, error: null })
      host.call('open', { file: path }).then((res) => {
        if (res && res.ok) store.set({ loading: false, current: { path: path, url: res.url }, running: true })
        else store.set({ loading: false, error: (res && res.error) || 'open failed' })
      }).catch((e) => store.set({ loading: false, error: String(e && e.message ? e.message : e) }))
    }

    const startResize = (e) => {
      e.preventDefault()
      document.body.setAttribute('data-hwb-dragging', '')
      const maxW = Math.max(MIN_WIDTH, window.innerWidth - 60)
      const onMove = (ev) => {
        const w = window.innerWidth - ev.clientX
        store.set({ panelWidth: Math.max(MIN_WIDTH, Math.min(w, maxW)) })
      }
      const onUp = () => {
        document.body.removeAttribute('data-hwb-dragging')
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    }

    const chevronUp = React.createElement('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
      React.createElement('path', { d: 'M18 15l-6-6-6 6' }))
    const chevronDown = React.createElement('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
      React.createElement('path', { d: 'M6 9l6 6 6-6' }))

    const Panel = () => {
      const s = useStore()
      React.useEffect(() => {
        const root = document.documentElement
        root.style.setProperty('--hwb-panel-width', s.open ? (s.panelWidth + 'px') : '0px')
        return () => { root.style.setProperty('--hwb-panel-width', '0px') }
      }, [s.open, s.panelWidth])
      React.useEffect(() => {
        if (!s.open) return
        refresh()
        const dispose = ctx.interval(refresh, 3000)
        return () => { if (dispose) dispose() }
      }, [s.open])
      if (!s.open) return null

      const assets = s.assets || []
      const currentPath = s.current && s.current.path ? s.current.path : ''
      const opts = assets.map((a) => React.createElement('option', { key: a.id || a.path, value: a.path }, basename(a.path)))
      const items = assets.map((a) => {
        const active = currentPath === a.path
        return React.createElement('div', { key: a.id || a.path, className: 'hwb-item' + (active ? ' active' : '') },
          React.createElement('div', { className: 'hwb-item-main' },
            React.createElement('div', { className: 'hwb-item-name' }, basename(a.path)),
            React.createElement('div', { className: 'hwb-item-path', title: a.path }, a.path),
          ),
          React.createElement('button', { type: 'button', className: 'hwb-item-btn', onClick: () => openFile(a.path) }, '打开'),
        )
      })

      return React.createElement('div', { className: 'hwb-panel', style: { width: s.panelWidth + 'px' }, role: 'dialog', 'aria-label': 'HTML Workbench' },
        React.createElement('div', { className: 'hwb-resize', title: '拖动调整宽度', onMouseDown: startResize }),
        React.createElement('div', { className: 'hwb-head' },
          React.createElement('span', { className: 'hwb-dot' + (s.running ? ' on' : '') }),
          React.createElement('div', { className: 'hwb-titlewrap' },
            React.createElement('div', { className: 'hwb-title' }, 'HTML Workbench'),
            React.createElement('div', { className: 'hwb-sub' }, s.running ? '服务运行中 · 拖动左边缘调整宽度' : '服务未就绪'),
          ),
          React.createElement('span', { className: 'hwb-spacer' }),
          React.createElement('button', { type: 'button', className: 'hwb-close', title: '关闭', onClick: () => store.set({ open: false }) },
            React.createElement('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' },
              React.createElement('path', { d: 'M18 6L6 18' }),
              React.createElement('path', { d: 'M6 6l12 12' }),
            ),
          ),
        ),
        React.createElement('div', { className: 'hwb-preview' },
          s.loading ? React.createElement('div', { className: 'hwb-hint' }, '正在启动 Workbench…')
            : s.current && s.current.url ? React.createElement('iframe', { className: 'hwb-frame', src: s.current.url, title: 'HTML Workbench' })
              : React.createElement('div', { className: 'hwb-hint' }, '从下方选择一个 HTML 文件开始编辑与预览'),
        ),
        React.createElement('div', { className: 'hwb-dock' },
          React.createElement('div', { className: 'hwb-dockbar' },
            React.createElement('select', {
              className: 'hwb-select',
              value: currentPath,
              onChange: (e) => { const v = e.target.value; if (v) openFile(v) },
            },
              React.createElement('option', { value: '', disabled: true }, assets.length ? '选择 HTML 文件…' : '暂无 HTML 产物'),
              opts,
            ),
            React.createElement('span', { className: 'hwb-count' }, assets.length + ' 个'),
            React.createElement('button', { type: 'button', className: 'hwb-docktoggle', title: s.expanded ? '收起列表' : '展开列表', onClick: () => store.set({ expanded: !s.expanded }) },
              s.expanded ? chevronDown : chevronUp,
            ),
          ),
          s.expanded ? React.createElement('div', { className: 'hwb-docklist' },
            items.length ? items : React.createElement('div', { className: 'hwb-dockempty' }, '暂无 HTML 产物 — 代理 write/edit 的 .html 文件会出现在这里。'),
            s.error ? React.createElement('div', { className: 'hwb-error' }, s.error) : null,
          ) : null,
        ),
      )
    }

    const Trigger = () => {
      const s = useStore()
      if (s.open) return null
      return React.createElement('button', {
        type: 'button',
        className: 'hwb-trigger',
        title: 'HTML Workbench',
        'aria-expanded': s.open,
        onClick: () => { store.set({ open: true }); refresh() },
      }, React.createElement('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
        React.createElement('rect', { x: 2, y: 4, width: 20, height: 14, rx: 2 }),
        React.createElement('path', { d: 'M8 21h8' }),
        React.createElement('path', { d: 'M12 18v3' }),
      ))
    }

    slots.inject('shell.overlay', () => slots.register(
      { name: 'shell.overlay', id: 'html-workbench-panel', order: 60, label: 'HTML Workbench' },
      () => React.createElement(Panel),
    ))

    slots.inject('shell.overlay', () => slots.register(
      { name: 'shell.overlay', id: 'html-workbench-trigger', order: 59, label: 'HTML Workbench 入口' },
      () => React.createElement(Trigger),
    ))
  },
}
