<p align="center">
  <img src="./assets/html-workbench.webp" alt="HTML Workbench：在浏览器中编辑本地 HTML 页面" width="1200">
</p>

# HTML Workbench

把 AI 生成的一份 HTML，变成可以在浏览器里继续编辑、预览和保存回磁盘的本地工作台。

它适合这样的工作方式：先让 AI 产出页面，再由人直接调整文案、图片、布局和样式；需要验证按钮、链接或业务交互时，切换到预览模式即可。修改仍然写回同一个 HTML 文件，AI 与人始终围绕同一份源文件协作。

## 它解决什么问题

- 不再在聊天窗口里反复描述“标题往下 20 像素”。
- 不需要为一份落地页临时搭建完整前端项目。
- 编辑时可视化操作，预览时保留真实页面交互。
- 服务只运行在本机 `127.0.0.1`，不会把文件暴露到局域网。
- 通过 revision 检查避免旧页面覆盖刚被 AI 或其他工具修改的文件。

## 推荐使用方式

默认生成一份单页、自闭环 HTML：HTML、CSS、JS 和必要视觉资源都在同一个 `.html` 文件里，不依赖 CDN 或额外项目目录。这样复制、打开、编辑和分享都更稳定。

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
