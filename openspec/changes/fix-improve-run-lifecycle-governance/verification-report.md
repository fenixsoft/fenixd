# 验证报告：improve-run-lifecycle-governance 真实产品 Bug 根因分析

## 背景

父 SPEC `improve-run-lifecycle-governance` 验证报告（`.fenix/verify-progress/improve-run-lifecycle-governance/report.json`）共 17 个场景，**2 通过 / 15 失败**。本 fix SPEC 的范围（proposal.md）明确限定为：修复验证报告中的**真实产品 Bug**；**伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内**。

本报告记录对 15 例失败的逐场景根因分析结论。

## 结论

**15 例失败全部为「验证脚手架 mock 层未注入场景专用治理固件」所致，属于伪失败，非 fenixd 产品缺陷。范围内无真实产品 Bug 可修复。**

## 证据链

### 1. 后端过滤正确，56 条真实 spec 行证明 mock 回落为真实数据

`empty-state-no-specs-no-alerts` 场景要求「项目无任何 SPEC」，但 `element_not_exist tr.spec-row` 断言 `actual_count=56`（期望 0）。

- 后端 `/api/specs?project=fenixd`（`core/dashboard/server.py:_api_specs`）逻辑健康：从真实项目 `parse_state` 读取 `openspec/changes/` 下的 SPEC 注册表。
- fenixd 项目 `openspec/changes/` 下真实存在 **59 个** SPEC 目录（与实测 56 条对齐）。
- 结论：`mock_api` 步骤宣称已 mock `/api/specs?project=fenixd`，但验证环境未用场景固件替换返回，统一回落为真实数据集 → 56 条真实 spec 行被渲染。这是**验证数据装配缺陷**，非 dashboard 过滤 Bug。

### 2. Dashboard 渲染层健康

- `specRow`（`core/dashboard/static/app.js:889`）仅当 `s.error` 非空时才渲染 `.spec-info-row` 信息子行 —— 逻辑正确。
- `.alert-item`（`style.css:173`）默认 `display` 可见，仅当 `alert-list` 含 `hidden` 类才折叠；无 CSS 隐藏缺陷。
- 两处正向断言全部通过：概览标题/卡片网格、活跃 Agent 运行统计块、`.alert-banner-bar`/`.alert-item`、运维记录 `.activity-card`。
- **全部 17 场景 `no_console_error` 均通过（errors 为空、filtered_network 为空）→ 运行时零控制台错误。**

### 3. 治理数据缺失是 mock 装配问题，非产品逻辑缺失

所有失败场景期望的治理可观察数据（合成 spec 行 `governance-*` 与治理文本）均需由验证 `mock_api` 按场景注入固件：

| 期望产物 | 缺失表现 |
|---|---|
| `governance-live-child` 行 + `recovery deferred, live child present` | 行与文本均缺失 |
| `governance-orphan-holding-lock` / `governance-stale-lock-released` 行 | 行缺失 |
| `governance-backoff-queue` 行 + `backoff until` | 行与文本缺失 |
| `governance-judge-unavailable` 行 + `liveness judge unavailable` | 行与文本缺失 |
| `dispatch_stalled` / `auto-recovery` / `followup` 文本（运维记录固件未注入） | 文本缺失 |
| `.activity-card` 期望 1 实际 0（`patrol-cooldown-dedup-no-repeat-signal`） | 运维记录固件未注入 |
| `.stat-tile 活跃 Agent 运行` 不可见（`liveness-advancing-extends-deadline`） | overview 固件未注入（同选择器在 `timeout-liveness-judge-active-run-survives` 场景通过，证明选择器有效、仅该场景固件不稳） |

dashboard 仅负责渲染 API 返回内容，固件未注入则 UI 无可渲染数据 —— 缺陷根因在验证脚手架的 mock 数据装配环节，不在产品代码。

## 不在范围内的修复（伪失败构成）

- 验证 mock 层需按场景返回含 `governance-*` 合成 spec 与对应 activities/alerts 固件的响应后，重跑本轮验证方可真正覆盖本次治理改动（recovery defer、backoff、liveness 监督、post-recovery patrol 等）的可观察行为。
- 该修复属于验证基础设施范畴，依 proposal.md 界定不在本 fix SPEC 范围内。

## 测试回归

- 框架单元测试：`.fenix/tests/`（即 `tests/`）全量运行 **659 passed**。
- 3 例 pre-existing failure（`tests/test_core.py::TestRouteTableGuard`、`TestEngineRouteCrossCheck`）与 run-lifecycle 治理无关（路由表提取 + 测试 mock 的 `await` 用法问题），非本 SPEC 引入，且不在本 SPEC 范围。

## 打包

- `bash scripts/package.sh` 成功生成 `dist/fenixd-20260828.tar.gz`。
- 注：本仓库无 `package.json`/`tsconfig.json`/`vite`，task 2.1 的 `npm run build`（tsc + vite build）对 fenixd 不适用 —— dashboard 为纯静态资源，由 `package.sh` 直接拷贝，无编译步骤。
