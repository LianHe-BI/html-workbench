# HTML Workbench Skill

把本地完整 HTML 页面放入 GrapesJS 可视化工作台，并把浏览器中的修改可靠地保存回原文件。最终可分发的 Skill 直接维护在 `skill/open-html-editor/`；最终用户只需要 Python 3.9 或更高版本，不需要 Node.js、npm 或任何 pip 包。

## 目录

```text
service/                 Python 服务与前端源码
skill/open-html-editor/  可直接复制安装的完整 Skill 产物（随源码提交）
build/                   将服务源码打入 Skill 的构建脚本
tests/                   Python 服务测试
```

## 开发与构建

生成独立 Skill：

```bash
npm run build
```

首次克隆项目后启用仓库自带的提交前检查：

```bash
npm run setup-hooks
```

提交前检查会重新构建 `skill/open-html-editor`。如果产物变化，提交会暂停；将最新的 Skill 目录加入提交后重试即可。也可以随时运行 `npm run check:skill` 检查源码和分发成品是否一致。

构建只把工作台自身的样式和逻辑内联到一个 `workbench.html`，并复制无第三方 Python 依赖的服务。GrapesJS 不再塞进 Skill：服务首次启动时会下载固定的 0.23.4 版本、校验 SHA-256 并放入用户缓存，后续离线复用。

下载顺序优先考虑中国网络：先尝试 npmmirror 的 npm 包，再依次尝试 CDNJS、jsDelivr 和 UNPKG。浏览器始终从本机服务加载资源，不直接依赖远程 CDN。首次启动需要约 1.2–2.9 MB 下载流量；所有来源都失败时会给出明确错误，不会打开残缺页面。

## 独立运行服务

```bash
python3 skill/open-html-editor/scripts/workbench.py serve
```

打开本地 HTML，并在服务未运行时自动启动：

```bash
python3 skill/open-html-editor/scripts/workbench.py open /absolute/path/page.html
```

命令输出 JSON，其中 `url` 是可直接访问的编辑地址。服务只监听 `127.0.0.1`，默认仅允许访问当前用户主目录内的 HTML 和相对资源。

默认缓存位于 `~/.cache/html-workbench/vendor/`（Windows 使用本地应用数据目录）。可用 `--vendor-cache` 指定其他位置。
