# Tasks: add-dashboard-help-center

## Deliverables

```yaml
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/help/index.tsx
  kind: new
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/package.json
  kind: modify
- path: core/dashboard/static/package-lock.json
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: docs/help/README.md
  kind: new
- path: docs/help/01-quick-start.md
  kind: new
- path: docs/help/02-concepts.md
  kind: new
- path: docs/help/03-lifecycle.md
  kind: new
- path: docs/help/04-cli.md
  kind: new
- path: docs/help/05-verification.md
  kind: new
- path: docs/help/06-governance.md
  kind: new
- path: docs/help/07-dashboard.md
  kind: new
- path: docs/help/08-config.md
  kind: new
- path: docs/help/09-artifacts.md
  kind: new
- path: docs/help/10-faq.md
  kind: new
- path: tests/test_dashboard_help_api.py
  kind: new
```

## 1. 后端文档读取 API

- [ ] 1.1 `core/dashboard/server.py` 新增 `GET /api/help/docs`：解析框架根（复用既有路径推导），返回 `docs/help/` 全部 `.md` 文件清单 `[{name, title}]`（标题取各文档首个一级标题；README 置顶、其余按文件名排序；目录缺失/为空返回空列表）。
- [ ] 1.2 新增 `GET /api/help/doc?name=<file>`：按名称返回单篇 Markdown 正文；文档名白名单校验（`[A-Za-z0-9._-]+\.md`）且解析后 real path 必须落在 `docs/help/` 内，非法名/不存在返回 404，目录缺失返回 404。
- [ ] 1.3 新增 `tests/test_dashboard_help_api.py` 单测：清单与正文正常路径、目录穿越拒绝（`..`）、非 .md 拒绝、不存在文档 404、`docs/help/` 缺失时空清单/404、标题解析正确。

## 2. 前端帮助中心

- [ ] 2.1 `config/routes.ts` 注册 `/help` 路由指向新页面；`src/app.tsx` 菜单数组在「运维」之后加「帮助」项（BookOutlined/QuestionCircleOutlined 图标）、面包屑 map 补 `help: '帮助'`。
- [ ] 2.2 新建 `src/pages/help/index.tsx`：桌面端左目录（文档清单，选中高亮）+ 右正文布局；URL query 同步当前文档（`#/help?doc=<name>`，缺省 README），刷新/直链可还原；目录点击切换文档并更新 URL。
- [ ] 2.3 Markdown 渲染：react-markdown + remark-gfm + 复用既有 `markdownComponents`；`code` 组件拦截 `language-mermaid` 块，动态 `import('mermaid')` 渲染 SVG，渲染失败回退显示原始代码文本；文档内指向其它帮助文档的相对链接改为页内切换（不整页跳出）。
- [ ] 2.4 容错与空态：`docs/help/` 缺失/清单为空显示「暂无帮助文档」空态；单篇读取失败在正文区显示错误提示、目录保持可用。
- [ ] 2.5 移动端适配（<768px，复用 useIsMobile + screen-xs 作用域模式）：目录与正文堆叠或抽屉切换，正文不溢出；PC 布局零回归。

## 3. 帮助文档内容（11 篇，全中文、图表 mermaid、以代码为准）

- [ ] 3.1 `README.md` 目录索引：10 篇导航 + 一句话简介 + 「新用户入门」「运维排查」阅读路径。
- [ ] 3.2 `01-quick-start.md` 快速上手：依赖清单、fenix-init、/fenix-setup、/fenix-new、自动循环观察（/fenix-status、Dashboard）、/fenix-approve 审批推送；端到端 mermaid 流程图。
- [ ] 3.3 `02-concepts.md` 核心概念与架构：闭环原理与唯一人工门禁、七类 Agent 角色分工（mermaid 架构图）、full vs fast-track 模式、worktree 隔离与 merge-back、多项目机制、术语表。
- [ ] 3.4 `03-lifecycle.md` SPEC 生命周期与状态机：10 状态 stateDiagram-v2 全景、每状态含义与进入/离开条件、打回与修复循环、冻结/解冻、daemon 重启中断恢复、门禁逃生门、STATE.md 与时间轴在哪看。
- [ ] 3.5 `04-cli.md` CLI 操作手册：7 个 /fenix-* skill 逐个详解（触发、交互流程、产出、示例）；bin/ 辅助脚本；fast-track/full 选择标准（影响面/模块数/UI/场景数四维）。
- [ ] 3.6 `05-verification.md` 验证体系：三步流水线（mermaid sequence）、verify.yaml 三段式契约与 BASE_URL 铁律、场景冻结、verdict 四分类与证据链、修复循环与 3 轮熔断、伪失败防线、验证报告与场景结果在哪看。
- [ ] 3.7 `06-governance.md` 调度与治理规则：优先级与并发、三类预算（impl_run_budget/token/daily_run_limit）与停靠、重试/退避/秒挂冷却、超时活性监督、自动恢复、merge 修复通道与熔断、fix 族谱收敛、告警分级流向（mermaid 图）、重启协议；每条规则附「对用户意味着什么」。
- [ ] 3.8 `07-dashboard.md` Dashboard 使用指南：概览/项目列表/SPEC 详情/设置/运维记录五页逐面板讲解、SPEC 行操作（优先级/冻结/归档/删除/呼叫 Admin）、告警处置、帮助页自身用法、安全边界（仅 127.0.0.1）。
- [ ] 3.9 `08-config.md` 配置参考：分级合并与 30s 热更新 vs 需重启、config.yaml 全键分组表（默认值/范围/生效方式）、「模板值与代码缺省不一致」澄清小节、Dashboard 设置页与配置键映射表。
- [ ] 3.10 `09-artifacts.md` 文件与数据地图：STATE.md 字段逐一解释、openspec artifacts 与 Deliverables 声明段、runs/verify-progress/admin_alerts/todo.md/PROJECT_LOG.md 逐文件说明、「出问题去哪查」对照表。
- [ ] 3.11 `10-faq.md` FAQ 与故障排查：SPEC 卡住/烧钱快/merge 冲突/验证反复失败/告警频响/daemon 拉起/安全人工接管等条目，每条「现象→根因→处置」，与各篇交叉链接。

## 4. 构建与收尾

- [ ] 4.1 `core/dashboard/static/package.json` 增加 mermaid 依赖（动态 import 用），`npm install` 更新 package-lock.json。
- [ ] 4.2 `npm run build` 重建 dist 并入库；构建产物包含 mermaid 独立 async chunk（非首屏 bundle）；本地起 dashboard 冒烟验证：菜单出现、文档加载、mermaid 图渲染、移动端布局。
- [ ] 4.3 对照 specs/help-docs 与 specs/help-center 的 Scenario 逐条自检；交叉链接目标存在性校验；README.md 过时点已在文档中澄清确认。
