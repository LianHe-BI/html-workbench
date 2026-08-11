# HTML Workbench Skill

把本地完整 HTML 页面放入 GrapesJS 可视化工作台，并把浏览器中的修改可靠地保存回原文件。项目源码与最终 Skill 分开维护；最终用户只需要 Python 3.9 或更高版本，不需要 Node.js、npm 或任何 pip 包。

## 目录

```text
service/                 Python 服务与前端源码
skill/open-html-editor/  Skill 指令与 UI 元数据
build/                   构建脚本
dist/open-html-editor/   可直接安装或复制的 Skill 产物
tests/                   Python 服务测试
```

## 开发与构建

安装前端构建依赖：

```bash
npm install
```

生成独立 Skill：

```bash
npm run build
```

构建会把 GrapesJS、工作台样式和前端逻辑内联到一个 `workbench.html`，并复制无第三方依赖的 Python 服务。

## 独立运行服务

```bash
python3 dist/open-html-editor/scripts/workbench.py serve
```

打开本地 HTML，并在服务未运行时自动启动：

```bash
python3 dist/open-html-editor/scripts/workbench.py open /absolute/path/page.html
```

命令输出 JSON，其中 `url` 是可直接访问的编辑地址。服务只监听 `127.0.0.1`，默认仅允许访问当前用户主目录内的 HTML 和相对资源。
