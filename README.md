<p align="center">
  <img src="./assets/html-workbench.webp" alt="HTML Workbench visual editor" width="1200">
</p>

<p align="center">
  <a href="#zh-cn">中文</a> · <a href="#english">English</a>
</p>

<a id="zh-cn"></a>

# HTML Workbench

把 AI 生成的一份 HTML，变成可以在浏览器里继续编辑、预览和保存回磁盘的本地工作台。

它适合这样的工作方式：先让 AI 产出页面，再由人直接调整文案、图片、布局和样式；需要验证按钮、链接或业务交互时，切换到预览模式即可。修改仍然写回同一个 HTML 文件，AI 与人始终围绕同一份源文件协作。

> **它不是 HTML 生成器。** 你可以用任何喜欢的方式生成 HTML：让任意 AI、设计工具、模板或手写代码产出文件；HTML Workbench 负责把这份现成的 HTML 转换为支持可视化编辑、预览，以及与 AI 实时协同修改的文档。

## 它解决什么问题

- 不再在聊天窗口里反复描述“标题往下 20 像素”。
- 不需要为一份落地页临时搭建完整前端项目。
- 编辑时可视化操作，预览时保留真实页面交互。
- 服务只运行在本机 `127.0.0.1`，不会把文件暴露到局域网。
- 通过 revision 检查避免旧页面覆盖刚被 AI 或其他工具修改的文件。

## 推荐使用方式

先用你选择的工具生成一份单页、自闭环 HTML，再交给 Workbench 打开和编辑。推荐让 HTML、CSS、JS 和必要视觉资源都在同一个 `.html` 文件里，不依赖 CDN 或额外项目目录；这样复制、打开、编辑和分享都更稳定。

页面中的交互也要按 Workbench 兼容规范生成：用稳定的语义标记定位元素，避免让 JS 依赖 `nth-child`、父子层级或节点顺序。Skill 会在打开页面前自动校验这些常见风险。

```text
AI 生成单个 HTML
        ↓
兼容性校验
        ↓
HTML Workbench 打开并编辑
        ↓
切换预览验证交互
        ↓
保存回原 HTML 文件
```

## 快速开始

最终用户只需要 Python 3.9 或更高版本，不需要 Node.js、npm 或 pip 包。

先检查新生成的单文件页面：

```bash
python3 skill/html-workbench/scripts/validate_html.py \
  --require-self-contained \
  /absolute/path/page.html
```

然后直接打开页面：

```bash
python3 skill/html-workbench/scripts/workbench.py open /absolute/path/page.html
```

`open` 是日常唯一需要使用的服务命令：如果服务已在本机运行，它会直接复用；否则会后台启动服务。命令输出 JSON，其中的 `url` 就是编辑地址。复制到任意浏览器打开即可；支持浏览器控制的 Agent 也可以自动打开它。

需要手动常驻运行服务时，才使用：

```bash
python3 skill/html-workbench/scripts/workbench.py serve
```

## 编辑与预览

- **编辑模式**：选择元素、修改文字、替换图片、调整样式或拖动内容。
- **预览模式**：使用当前未保存的编辑结果重新生成页面，让链接、按钮和页面脚本按普通网页方式运行。
- **保存**：把编辑结果安全写回原文件；若磁盘文件已被外部更新，会停止覆盖并提示冲突。

## HTML Workbench Skill

可直接分发和安装的 Skill 位于 [skill/html-workbench](./skill/html-workbench/)。它会引导 Agent：

1. 生成完整、单文件 HTML；
2. 按兼容规范组织交互；
3. 运行校验器并修复错误；
4. 用 `open` 复用或启动服务；
5. 返回可点击的编辑地址，并说明服务是否已复用。

详细规则见 [生成规范](./skill/html-workbench/references/editable-html-guidelines.md) 与 [校验规则](./skill/html-workbench/references/validation-rules.md)。

## 开发与打包

源码保留在 `service/`、`build/` 和 `tests/`；可分发 Skill 始终维护在 `skill/html-workbench/`。

```bash
npm run build
npm test
```

构建会把前端工作台打包为一个 `workbench.html`，并复制无第三方依赖的 Python 服务和校验器到 Skill。GrapesJS 在服务首次启动时下载固定版本、校验 SHA-256 后写入本机缓存；下载顺序优先使用 npmmirror，再回退到其他公共源，后续启动可离线复用。

<a id="english"></a>

# HTML Workbench

Turn an existing HTML page into a local workspace where people can edit it visually, preview its interactions, and save changes back to disk.

The workflow is simple: let AI create the page, refine copy, images, layout, and styling directly in the browser, then switch to Preview to test buttons, links, and page behavior. Both people and AI continue to work from the same HTML source file.

> **HTML Workbench is not an HTML generator.** Create HTML however you prefer—with any AI, design tool, template, or hand-written code—then give that file to HTML Workbench. It turns the existing document into a visual editor with preview and real-time collaboration against the same source file.

## What it solves

- Avoid repeated chat-based requests such as “move this title down by 20 pixels.”
- Skip scaffolding a full frontend project for a single landing page.
- Edit visually while preserving real page interactions in Preview mode.
- Keep the service on local `127.0.0.1`; files are never exposed to the LAN.
- Use revision checks to prevent an outdated editor state from overwriting changes made by AI or another tool.

## Recommended workflow

First create one self-contained HTML page with the tool of your choice, then open it in Workbench. Keep its HTML, CSS, JavaScript, and required visual assets in one `.html` file, without a CDN or extra project directory. This makes the page easier to copy, open, edit, and share reliably.

Generate interactions according to the Workbench compatibility rules. Use stable semantic markers instead of relying on `nth-child`, DOM ancestry, or node ordering. The Skill checks these common risks before opening the page.

```text
AI generates one HTML file
        ↓
Compatibility validation
        ↓
Open and edit in HTML Workbench
        ↓
Switch to Preview and verify interactions
        ↓
Save back to the original HTML file
```

## Quick start

End users need Python 3.9 or later—no Node.js, npm, or pip packages.

Validate a newly generated single-file page:

```bash
python3 skill/html-workbench/scripts/validate_html.py \
  --require-self-contained \
  /absolute/path/page.html
```

Then open it:

```bash
python3 skill/html-workbench/scripts/workbench.py open /absolute/path/page.html
```

`open` is the only service command needed in normal use. It reuses a running local service when available, or starts one in the background when needed. Its JSON output contains the editor `url`; open that URL in any browser. Agents with browser control can open it automatically.

Only use the following command when you explicitly want to manage a foreground service:

```bash
python3 skill/html-workbench/scripts/workbench.py serve
```

## Edit and preview

- **Edit mode**: Select elements, change text, replace images, adjust styles, and move content.
- **Preview mode**: Rebuild the page from the current unsaved edits so links, buttons, and page scripts run as they would in a normal browser.
- **Save**: Write changes safely to the original file. If it changed on disk, Workbench stops rather than overwriting it.

## HTML Workbench Skill

The distributable Skill lives in [skill/html-workbench](./skill/html-workbench/). It guides an Agent to:

1. Generate a complete, single-file HTML page.
2. Structure interactions according to the compatibility rules.
3. Run the validator and fix errors.
4. Reuse or start the service through `open`.
5. Return a clickable editor URL and report whether the service was reused.

Read the [generation guide](./skill/html-workbench/references/editable-html-guidelines.md) and [validation rules](./skill/html-workbench/references/validation-rules.md) for details.

## Development and packaging

Source code stays in `service/`, `build/`, and `tests/`; the distributable Skill is maintained in `skill/html-workbench/`.

```bash
npm run build
npm test
```

The build bundles the workbench frontend into one `workbench.html` and copies the dependency-free Python service and validator into the Skill. GrapesJS is downloaded at first service launch, hash-verified, and cached locally. The download sequence prefers npmmirror, then falls back to other public sources; later launches can reuse the local cache offline.
