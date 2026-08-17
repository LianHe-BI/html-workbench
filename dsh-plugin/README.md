# HTML Workbench DSH Plugin

在 DeepSeek Harness（DSH）的右侧栏预览并可视化编辑 agent 生成的 HTML 文件。它复用（或拉起）HTML Workbench 的本地 Python 服务，把 GrapesJS 编辑器内嵌到页面 iframe 里，直接改文案/样式/图片、切 Preview 验证交互、Save 写回磁盘。

> 只托管源码，不做编译/打包。插件通过 `shell` 服务拉起仓库里**已生成**的 runnable workbench（`skill/html-workbench/scripts/workbench.py`，由根目录 `npm run build` 从 `service/` 生成）。

## 目录结构

```
dsh-plugin/
├── src/
│   ├── host.js      # Host 半函数体（返回 { inject, apply }）——动态与静态共用
│   ├── client.js    # Client 半函数体（返回 { inject, apply }）——动态与静态共用
│   └── index.js     # 静态 Host 入口：读取 host.js 并 re-export
├── dsh.plugin.json  # 插件清单
├── cordis.patch.yml # 静态装载的 profile 补丁（--patch）
├── package.json
└── README.md
```

`src/host.js` 和 `src/client.js` 里的 `return { ... }` 是**唯一事实源**——同一段函数体同时服务两种装载方式。

## 装载方式

### 动态热装载（开发期热调试，当前使用中）

把 `src/host.js` / `src/client.js` 的文本分别作为 `code.host` / `code.client` 提交给 `cordis_define`，再 `cordis_run`。零停机，源码只存在于运行中的 DSH 进程里，进程重启后需重新装载。

`host.js` 默认用本机仓库内的 `skill/html-workbench/scripts/workbench.py` 拉起服务。

### 静态装载（后续发布 NPM 时再接入）

`cordis.patch.yml` + `package.json` 的 `dsh.bundle` 已就绪；Client 半的静态 bundle（`window.__ModuleLoader__.load`）尚未接入，动态 Client 已可用。

## 服务生命周期（副作用管理）

- **注册时**：`apply` 里异步 `startService()`，先 `health` 探测 `4317`；已在运行则复用（不认领），否则 `shell.start` 后台拉起 `workbench.py serve`。
- **卸载时**：`ctx.effect` 的 disposer `kill()` 掉本插件自己启动的那个进程；复用的服务不误杀。

## RPC 接口（Client → Host）

| method   | 入参        | 返回                                   |
| -------- | ----------- | -------------------------------------- |
| `list`   | —           | `{ ok, running, owned, port, assets }` |
| `status` | —           | `{ ok, running, owned, port, info }`   |
| `open`   | `{ file }`  | `{ ok, url, reused, port }`            |

`assets` 来自监听 `tools/result`，收集 `write`/`edit` 工具产出的 `.html` 文件路径。
