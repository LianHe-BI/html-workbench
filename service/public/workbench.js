'use strict'

const grapesjs = window.grapesjs
const fileInput = document.querySelector('#file-input')
const fileName = document.querySelector('#file-name')
const status = document.querySelector('#status')
const saveButton = document.querySelector('#save-button')
const canvasArea = document.querySelector('.canvas-area')
const canvasStage = document.querySelector('#canvas-stage')
const viewport = document.querySelector('#canvas-viewport')
const fitButton = document.querySelector('#fit-button')
const fileMenuButton = document.querySelector('#file-menu-button')
const filePopover = document.querySelector('#file-popover')
const controlPanel = document.querySelector('#control-panel')
const closePanelButton = document.querySelector('#close-panel-button')
const pinPanelButton = document.querySelector('#pin-panel-button')
const panelTitle = document.querySelector('#panel-title')
const panelButtons = [...document.querySelectorAll('[data-panel]')]
const panelContents = [...document.querySelectorAll('[data-panel-content]')]
const attributesPanel = document.querySelector('#attributes-panel')
const srcInput = document.querySelector('#src-input')
const altInput = document.querySelector('#alt-input')
const hrefInput = document.querySelector('#href-input')
const workbench = document.querySelector('.workbench')
const modeButtons = [...document.querySelectorAll('[data-mode]')]
const previewFrame = document.querySelector('#preview-frame')

let editor
let activeFile = ''
let assetBase = ''
let revision = ''
let bodyScripts = []
let sourceCss = ''
let links = []
let headScripts = []
let htmlAttributes = {}
let bodyAttributes = {}
let appliedHtmlAttributes = new Set()
let appliedBodyAttributes = new Set()
let eventSource
let saveTimer
let applyingDocument = false
let dirty = false
let canvasWidth = 768
let fitCanvas = true
let activePanel = ''
let panelPinned = false
let workbenchMode = 'edit'

function setStatus(text, state = 'idle') {
  status.querySelector('b').textContent = text
  status.dataset.state = state
  saveButton.disabled = state === 'saving'
}

function api(route) {
  return `${route}?file=${encodeURIComponent(activeFile)}`
}

function setFilePopover(open) {
  filePopover.hidden = !open
  fileMenuButton.setAttribute('aria-expanded', String(open))
}

function setPanelPinned(pinned) {
  panelPinned = pinned
  pinPanelButton.setAttribute('aria-pressed', String(pinned))
  pinPanelButton.setAttribute('aria-label', pinned ? '取消固定面板' : '固定面板')
  pinPanelButton.title = pinned ? '取消固定' : '固定面板'
  document.querySelector('.workbench').classList.toggle('panel-pinned', pinned && !controlPanel.hidden)
  requestAnimationFrame(updateCanvasScale)
}

function closePanel() {
  controlPanel.hidden = true
  activePanel = ''
  panelButtons.forEach((button) => button.classList.remove('active'))
  setPanelPinned(false)
}

function openPanel(name) {
  if (activePanel === name && !controlPanel.hidden) return closePanel()
  activePanel = name
  controlPanel.hidden = false
  panelTitle.textContent = name === 'styles' ? '调整样式' : '添加内容'
  panelButtons.forEach((button) => button.classList.toggle('active', button.dataset.panel === name))
  panelContents.forEach((content) => { content.hidden = content.dataset.panelContent !== name })
  setPanelPinned(name === 'styles')
  requestAnimationFrame(() => {
    updateCanvasScale()
    editor?.refresh()
  })
}

function escapeAttribute(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function serializeAttributes(attributes = {}) {
  return Object.entries(attributes).map(([name, value]) => ` ${name}="${escapeAttribute(value)}"`).join('')
}

function serializeHeadScript(source) {
  return `<script${serializeAttributes(source.attributes)}>${source.content || ''}</script>`
}

function getBodyHtml() {
  // GrapesJS 的 wrapper 组件 tagName 为 'body'，editor.getHtml() 返回
  // <body>...</body>。服务端校验禁止 bodyHtml 包含 html/head/body/script
  // 标签，预览文档也已有 <body> 包装，因此这里取 wrapper 的 innerHTML。
  const wrapper = editor.getWrapper()
  return wrapper.getInnerHTML ? wrapper.getInnerHTML() : editor.getHtml().replace(/^<body\b[^>]*>/i, '').replace(/<\/body>\s*$/i, '')
}

function buildPreviewDocument() {
  const previewBase = new URL(assetBase, location.origin).href
  const stylesheets = links.map((href) => `<link rel="stylesheet" href="${escapeAttribute(href)}">`).join('\n')
  const scripts = headScripts.map(serializeHeadScript).join('\n')
  const overrideCss = editor.getCss()
  const previewHelpers = `<script>
document.addEventListener('click', function (event) {
  const link = event.target.closest && event.target.closest('a[href^="#"]')
  if (!link) return
  const fragment = link.getAttribute('href').slice(1)
  if (!fragment) return
  const target = document.getElementById(decodeURIComponent(fragment))
  if (!target) return
  event.preventDefault()
  target.scrollIntoView()
}, false)
</script>`
  return `<!doctype html>
<html${serializeAttributes(htmlAttributes)}>
<head>
  <meta charset="utf-8">
  <base href="${escapeAttribute(previewBase)}">
  ${stylesheets}
  <style>${sourceCss}</style>
  <style data-grapesjs-overrides>${overrideCss}</style>
  ${scripts}
</head>
<body${serializeAttributes(bodyAttributes)}>
${getBodyHtml()}
${bodyScripts.join('\n')}
${previewHelpers}
</body>
</html>`
}

function setWorkbenchMode(nextMode) {
  if (!editor || nextMode === workbenchMode || !['edit', 'preview'].includes(nextMode)) return
  workbenchMode = nextMode
  const previewing = workbenchMode === 'preview'
  workbench.dataset.mode = workbenchMode
  modeButtons.forEach((button) => {
    const active = button.dataset.mode === workbenchMode
    button.classList.toggle('active', active)
    button.setAttribute('aria-pressed', String(active))
  })
  if (previewing) {
    closePanel()
    setFilePopover(false)
    editor.select(null)
    previewFrame.srcdoc = buildPreviewDocument()
    previewFrame.hidden = false
  } else {
    previewFrame.hidden = true
    previewFrame.srcdoc = ''
  }
  requestAnimationFrame(() => {
    updateCanvasScale()
    editor.refresh()
  })
}

function updateCanvasScale() {
  if (!canvasArea || !viewport) return
  const styles = getComputedStyle(canvasArea)
  const availableWidth = canvasArea.clientWidth - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight)
  const availableHeight = canvasArea.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom)
  const scale = fitCanvas ? Math.min(1, availableWidth / canvasWidth) : 1
  viewport.style.width = `${canvasWidth}px`
  viewport.style.height = `${Math.max(320, availableHeight / scale)}px`
  viewport.style.zoom = String(scale)
  viewport.dataset.scale = scale.toFixed(3)
  canvasStage.style.minHeight = `${Math.max(320, availableHeight)}px`
  requestAnimationFrame(() => editor?.refresh())
}

function applySourceAttributes(element, attributes, appliedNames) {
  for (const name of appliedNames) element.removeAttribute(name)
  const nextNames = new Set()
  for (const [name, value] of Object.entries(attributes || {})) {
    element.setAttribute(name, value)
    nextNames.add(name)
  }
  return nextNames
}

function componentFromCanvasElement(element) {
  const node = element?.closest?.('[data-gjs-type][id]')
  if (!node) return null
  return editor.getWrapper().find(`#${node.id}`)[0] || null
}

async function injectSourceAssets() {
  const document = editor?.Canvas.getDocument()
  if (!document) return
  document.querySelectorAll('[data-source-asset]').forEach((node) => node.remove())
  appliedHtmlAttributes = applySourceAttributes(document.documentElement, htmlAttributes, appliedHtmlAttributes)
  appliedBodyAttributes = applySourceAttributes(document.body, bodyAttributes, appliedBodyAttributes)
  const base = document.createElement('base')
  base.href = new URL(assetBase, location.origin).href
  base.dataset.sourceAsset = 'true'
  document.head.prepend(base)

  for (const source of headScripts) {
    const script = document.createElement('script')
    for (const [name, value] of Object.entries(source.attributes || {})) script.setAttribute(name, value)
    script.dataset.sourceAsset = 'true'
    if (!script.src) {
      script.textContent = source.content || ''
      document.head.append(script)
      continue
    }
    await new Promise((resolve) => {
      script.addEventListener('load', resolve, { once: true })
      script.addEventListener('error', resolve, { once: true })
      document.head.append(script)
    })
  }
  for (const href of links) {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = href
    link.dataset.sourceAsset = 'true'
    document.head.append(link)
  }
  const style = document.createElement('style')
  style.dataset.sourceAsset = 'true'
  style.textContent = sourceCss
  document.head.append(style)
  const interactionStyle = document.createElement('style')
  interactionStyle.dataset.sourceAsset = 'true'
  interactionStyle.textContent = '[data-gjs-type="default"]:empty{pointer-events:none!important}'
  document.head.append(interactionStyle)

  if (!document.documentElement.dataset.workbenchInteractionBound) {
    document.documentElement.dataset.workbenchInteractionBound = 'true'
    document.addEventListener('click', (event) => {
      if (workbenchMode !== 'edit') return
      const component = componentFromCanvasElement(event.target)
      if (component) editor.select(component)
    }, true)
    document.addEventListener('dblclick', (event) => {
      if (workbenchMode !== 'edit') return
      const component = componentFromCanvasElement(event.target)
      if (!component) return
      editor.select(component)
      if (component.get('editable')) component.trigger('active', event)
    }, true)
  }

}

function initEditor() {
  editor = grapesjs.init({
    container: '#gjs',
    height: '100%',
    width: 'auto',
    storageManager: false,
    jsInHtml: false,
    panels: { defaults: [] },
    blockManager: {
      appendTo: '#blocks-panel',
      blocks: [
        { id: 'text', label: '文本', category: '基础', content: '<p data-gjs-type="text">双击编辑这段文字</p>' },
        { id: 'section', label: '区块', category: '基础', content: '<section style="padding:32px"><h2>新章节</h2><p>在这里补充内容。</p></section>' },
        { id: 'image', label: '图片', category: '基础', content: { type: 'image' }, select: true, activate: true },
      ],
    },
    styleManager: {
      appendTo: '#styles-panel',
      sectors: [
        { name: '排版', open: true, properties: ['font-family', 'font-size', 'font-weight', 'color', 'line-height', 'letter-spacing', 'text-align'] },
        { name: '空间', open: false, properties: ['margin', 'padding'] },
        { name: '尺寸', open: false, properties: ['width', 'height', 'max-width', 'min-height'] },
        { name: '外观', open: false, properties: ['background-color', 'border', 'border-radius', 'opacity'] },
        { name: '布局', open: false, properties: ['display', 'flex-direction', 'justify-content', 'align-items', 'gap'] },
      ],
    },
    selectorManager: { componentFirst: true },
    canvas: { frameStyle: 'html{background:#f4f4f5}body{min-height:100vh}' },
  })
  window.__GRAPESJS_WORKBENCH__ = { editor }
  editor.on('load', () => void injectSourceAssets())
  editor.on('update', scheduleSave)
  // GrapesJS 的 RTE 文本编辑走 storeData → sync:content（noCount:true）路径，
  // 不触发 editor 的 'update' 事件（changesCount 不增加）。但组件模型的
  // Backbone change 事件不受 noCount 影响，会转发为 component:update，
  // 因此补充监听该事件以覆盖文本内容编辑场景。
  editor.on('component:update', scheduleSave)
  editor.on('component:selected', updateAttributePanel)
}

function updateAttributePanel(component) {
  const tag = component?.get('tagName')
  const attributes = component?.getAttributes?.() || {}
  const image = tag === 'img'
  const link = tag === 'a'
  attributesPanel.hidden = !image && !link
  srcInput.parentElement.hidden = !image
  altInput.parentElement.hidden = !image
  hrefInput.parentElement.hidden = !link
  srcInput.value = attributes.src || ''
  altInput.value = attributes.alt || ''
  hrefInput.value = attributes.href || ''
}

function scheduleSave() {
  if (applyingDocument || workbenchMode !== 'edit' || !activeFile) return
  dirty = true
  setStatus('等待自动保存', 'dirty')
  clearTimeout(saveTimer)
  saveTimer = setTimeout(save, 500)
}

async function save() {
  if (!editor || !activeFile || !revision || !dirty) return
  clearTimeout(saveTimer)
  setStatus('正在写入磁盘', 'saving')
  try {
    const response = await fetch(api('/api/document'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        baseRevision: revision,
        bodyHtml: getBodyHtml(),
        css: editor.getCss(),
        bodyScripts,
      }),
    })
    const result = await response.json()
    if (response.status === 409) {
      setStatus('磁盘有更新，已停止覆盖', 'conflict')
      dirty = false
      await applyDocument(result.document)
      return
    }
    if (!response.ok) throw new Error(result.message || result.error)
    revision = result.revision
    bodyScripts = result.bodyScripts || bodyScripts
    dirty = false
    setStatus('已与磁盘同步', 'saved')
  } catch (error) {
    setStatus(error.message || '保存失败', 'error')
  }
}

async function applyDocument(document) {
  activeFile = document.filePath
  assetBase = document.assetBase
  revision = document.revision
  bodyScripts = document.bodyScripts || []
  sourceCss = document.sourceCss || ''
  links = document.links || []
  headScripts = document.headScripts || []
  htmlAttributes = document.htmlAttributes || {}
  bodyAttributes = document.bodyAttributes || {}
  fileInput.value = activeFile
  fileName.textContent = document.fileName
  fileName.title = activeFile
  applyingDocument = true
  clearTimeout(saveTimer)
  dirty = false
  editor.setComponents(document.bodyHtml)
  editor.setStyle(document.overrideCss || '')
  await injectSourceAssets()
  requestAnimationFrame(() => editor.refresh())
  setTimeout(() => {
    clearTimeout(saveTimer)
    dirty = false
    applyingDocument = false
  }, 250)
}

async function loadFile(file = activeFile) {
  if (!file) return setStatus('请输入 HTML 文件路径', 'error')
  if (dirty) await save()
  setStatus('正在读取磁盘文件', 'saving')
  try {
    activeFile = file
    const response = await fetch(api('/api/document'))
    const document = await response.json()
    if (!response.ok) throw new Error(document.message || document.error)
    await applyDocument(document)
    dirty = false
    connectEvents()
    const url = new URL(location.href)
    url.searchParams.set('file', activeFile)
    history.replaceState({}, '', url)
    setFilePopover(false)
    setStatus('已与磁盘同步', 'saved')
  } catch (error) {
    setStatus(error.message || '加载失败', 'error')
  }
}

function connectEvents() {
  eventSource?.close()
  eventSource = new EventSource(api('/api/events'))
  eventSource.onmessage = async (event) => {
    const update = JSON.parse(event.data)
    if (!update.revision || update.revision === revision) return
    if (dirty) return setStatus('磁盘已更新，请先处理当前编辑', 'conflict')
    await loadFile(activeFile)
  }
  eventSource.onerror = () => setStatus('文件监听暂时断开', 'error')
}

function saveAttribute(name, input) {
  const selected = editor?.getSelected()
  if (!selected) return
  selected.addAttributes({ [name]: input.value })
  scheduleSave()
}

initEditor()
document.querySelector('#open-button').addEventListener('click', () => loadFile(fileInput.value.trim()))
fileInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadFile(fileInput.value.trim()) })
fileMenuButton.addEventListener('click', () => setFilePopover(filePopover.hidden))
panelButtons.forEach((button) => button.addEventListener('click', () => openPanel(button.dataset.panel)))
modeButtons.forEach((button) => button.addEventListener('click', () => setWorkbenchMode(button.dataset.mode)))
closePanelButton.addEventListener('click', closePanel)
pinPanelButton.addEventListener('click', () => setPanelPinned(!panelPinned))
document.querySelector('#undo-button').addEventListener('click', () => editor.UndoManager.undo())
document.querySelector('#redo-button').addEventListener('click', () => editor.UndoManager.redo())
saveButton.addEventListener('click', save)
document.querySelector('#replace-image-button').addEventListener('click', () => {
  const selected = editor.getSelected()
  if (!selected || selected.get('tagName') !== 'img') return setStatus('请先选中图片', 'error')
  const next = window.prompt('输入新的图片 URL 或相对路径', selected.getAttributes().src || '')
  if (next == null) return
  selected.addAttributes({ src: next })
  scheduleSave()
})
document.querySelectorAll('[data-width]').forEach((button) => button.addEventListener('click', () => {
  canvasWidth = Number(button.dataset.width)
  document.querySelectorAll('[data-width]').forEach((item) => item.classList.toggle('active', item === button))
  updateCanvasScale()
}))
fitButton.addEventListener('click', () => {
  fitCanvas = !fitCanvas
  fitButton.classList.toggle('active', fitCanvas)
  fitButton.setAttribute('aria-pressed', String(fitCanvas))
  updateCanvasScale()
})
canvasArea.addEventListener('click', (event) => {
  if (event.target === canvasArea || event.target === canvasStage) {
    if (!panelPinned) closePanel()
    setFilePopover(false)
  }
})
document.addEventListener('pointerdown', (event) => {
  if (!filePopover.hidden && !event.target.closest('.file-cluster')) setFilePopover(false)
})
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return
  setFilePopover(false)
  if (!panelPinned) closePanel()
})
new ResizeObserver(updateCanvasScale).observe(canvasArea)
srcInput.addEventListener('change', () => saveAttribute('src', srcInput))
altInput.addEventListener('change', () => saveAttribute('alt', altInput))
hrefInput.addEventListener('change', () => saveAttribute('href', hrefInput))

const initialFile = new URLSearchParams(location.search).get('file')
if (initialFile) loadFile(initialFile)
else setStatus('输入路径或使用 ?file= 打开 HTML', 'idle')
updateCanvasScale()
