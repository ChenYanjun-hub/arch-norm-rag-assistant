# W7 · 答案 Markdown 渲染（含引用角标保全）— 启示 86

**结论**：⭐ 引入 `react-markdown` + `remark-gfm`（**经批准的新依赖**），把答案正文从纯文本渲染升级为
Markdown 渲染：表格、粗体、列表、引用块全部生效。
**关键约束：`[N]` 引用角标必须在 Markdown 渲染后依然是可点 chip**——这是红线 2（可追溯）的载体，
不能被 md 渲染吃掉。沉淀 **启示 86**（升级渲染层时，先identify"哪些交互是红线载体"）。

---

## 一、动机

Agent 可见化上线后暴露：工具 Agent 的答案常含 Markdown 表格，但前端是 `white-space: pre-wrap` 纯文本，
表格显示成 `| 序号 | 规范号 |` 的原始管道符；常规 RAG 答案里的 `**结论：**` 也显示成字面星号。
产品定位是"像查法条"，排版可读性直接影响专业感。

## 二、依赖决策（CLAUDE.md G.1 记录）

| | |
|---|---|
| 新增依赖 | `react-markdown@10` + `remark-gfm@4`（表格需 GFM）|
| 批准 | ✅ 用户明确批准（"我们先走A"）|
| 代价 | bundle 222KB → 378KB（gzip 70 → 116KB）|
| 备选 | 手写 mini markdown 解析器（零依赖，但表格/嵌套易错，维护成本更高）→ 未采用 |

## 三、实现要点：红线载体的保全

`renderWithCitations` 原来直接吃整段字符串。改成 Markdown 后，文本被 md AST 拆成了许多节点，
**如果不处理，`[1]` 会变成普通文字，引用联动全废**（红线 2）。

方案：给 `react-markdown` 传 `components` 覆盖，所有含文本的元素（p/li/strong/em/td/th/h*）
的 children 都过一遍 `withCitations()` —— 用 `Children.map` 把字符串子节点转成 chip，其余原样透传。

```
p/li/strong/em/td/th/h* → withCitations(children) → [N] 仍是可点 chip
table → 包一层 .cn-md-table-wrap（overflow-x:auto，宽表不撑破卡片）
a → target=_blank + rel=noopener
```

样式集中在 `design.css` 的 `.cn-md-*`（沿用项目"内联样式最少、样式集中"的约定）。

## 四、🎯 验证（浏览器实测）

| 验证项 | 结果 |
|---|---|
| 工具答案的 Markdown 表格 | ✅ 渲染为真表格（表头/边框/斑马纹），6 部消防规范整齐 |
| 常规答案粗体 `**依据：**` | ✅ 渲染为粗体，不再显示字面 `**` |
| **`[N]` 引用 chip 仍在** | ✅ 10 个 chip 全部渲染 |
| **chip 点击仍联动** | ✅ 点击后 `is-active` 正确应用（红线 2 完好）|
| Console 报错 | ✅ 无 |
| TS 编译 / build | ✅ 通过 |

> TS 细节：`components` 映射必须标注 `Components` 返回类型，否则解构参数推断为 `any`、
> 且 `a` 的 `href` 可选性与 react-markdown 类型不兼容（首次 build 即报错，已修）。

## 五、🎓 启示 86 · 升级渲染层前，先identify"哪些交互是红线载体" ⭐

换渲染方式看起来是纯视觉改动，但**正文里承载业务红线的交互元素会被一起重写**。
本项目的 `[N]` chip 不是装饰——它是"每条事实可回链到具体规范条文"的唯一入口（红线 2）。
Markdown 渲染如果无脑替换，排版变好了、可追溯性没了，**净损失**。

**对 AIPM 转行的启示**：
- **改造前先问"这一层里，什么是不能丢的"**。视觉升级的验收标准不只是"好看了"，
  而是"好看了**且**原有关键交互一个不少"——我的验收清单里，chip 可点性和表格渲染是同等权重。
- **验收要测交互，不能只截图**。截图能看到 chip 还在，但看不出它还能不能点——
  必须实际点一次、断言状态变化。可见 ≠ 可用。

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `frontend/package.json` | +react-markdown@10 +remark-gfm@4（经批准）|
| `frontend/src/components/ChatMessage.tsx` | Markdown 渲染 + `withCitations`/`mdComponents`（保 chip）|
| `frontend/src/styles/design.css` | +`.cn-md-*` 样式（表格/引用块/列表/代码）|
| `docs/devlog/2026-W7_markdown_render.md` | 本文件 |

---

**日志版本**：v1.0
**最后更新**：2026-W7（agent 深化 · Markdown 渲染）
**累计洞察**：**86 个**（+启示 86 渲染层升级要保红线载体）
**项目状态**：答案支持 Markdown（表格/粗体/列表）· 引用 chip 与联动完好 · bundle gzip 70→116KB
