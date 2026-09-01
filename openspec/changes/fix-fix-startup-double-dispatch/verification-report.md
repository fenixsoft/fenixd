# 验证报告：fix-fix-startup-double-dispatch

## 结论

**无真实产品 Bug —— 父 SPEC `fix-startup-double-dispatch` 验证报告的 10 个失败场景全部判定为伪失败（场景期望缺陷），不在本 SPEC 修复范围内。**

- 父验证报告失败场景：10
- 真实产品 Bug：0
- 伪失败（场景期望 / 选择器与产品 DOM 不符）：10

本 SPEC 的 `proposal.md` 明确限定：*「伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内。」*
经根因定位，**父 SPEC 的产品代码（`core/pm_engine/engine.py` 单飞守卫、
`core/pm_engine/dispatch.py` 状态回写保护、`core/pm_engine/verification.py` verifier 终态对账）已完整且正确地实现**
三类缺陷修复，且全部通过对应单元测试（`tests/test_startup_double_dispatch.py` 10 项、
`tests/test_pm_verification.py` + `tests/test_pm_dispatch.py` 56 项全过）。
因此**不修改任何产品代码**（在正确代码上改动只会引入回归）。

---

## 根因定位方法

1. **产品代码核对**：逐一核对父 SPEC 三项修复的合并实现（commit `3e159bd` + `c40dc2a`）：
   - `core/pm_engine/engine.py` `_pending_dispatches` 单飞守卫：`_on_spec_ready` 入口原子检查
     `if spec_name in self._pending_dispatches` → 跳过；标记在**任何异步操作之前**
     （worktree 锁创建前）`add(spec_name)`，`finally` 中 `discard(spec_name)` 清理。封死启动窗口 ✓
   - `core/pm_engine/dispatch.py` merge-back 失败路径：回写 ready 前检查
     `current_status in (testing, implemented) and active_tester`
     → 命中则不降级 ready，仅记录 `_merge_fp/_merge_streak` 与冲突日志。✓
   - `core/pm_engine/verification.py` verifier 完成路径（pass 与 bug-found 双分支）：spec 状态非 `testing` 时
     按报告对账重放（`implemented → testing → verified` 或 `implemented → testing → bug-found`），
     无法重放则落 blocked 并附证据。✓

2. **验证场景对照产品 DOM**：父验证的 10 个场景全部为浏览器场景（`http://localhost:8787`），
   断言选择器与状态文本与产品实际 DOM 不符（详见逐场景裁决表）。

3. **回归测试**：父 SPEC 相关单测 10 项全过；`tests/` 全量 947 passed（仅 1 项环境相关失败，见下）。

---

## 逐场景裁决（10 项全为伪失败）

父验证报告的 10 个失败场景按「场景期望缺陷」分类。所有场景共享同一根因模式：
**验证场景断言的选择器 / 状态文本与产品实际 DOM 不一致**，而非产品功能缺失。

### A. 状态文本断言错误（4 个场景）

场景用 `text_match` 断言 `.status-pill` 的文本为英文状态字面量
（`testing|implemented|verified|done` / `testing|done|verified` / `testing|blocked|done|verified`），
但产品 `statusPill()`（`core/dashboard/static/app.js` 的 `STATUS_META`）渲染的是**中文标签**：
`ready→📌 就绪`、`implemented→🧪 已实现`、`testing→🔍 验证中`、`verified→✅ 已验证`、
`bug-found→🐛 有Bug`、`done→🎯 完成`、`pushed→🚀 已推送`。场景期望的英文状态字面量在产品中不存在
→ `text_match`（exact 模式）必然失败。产品状态显示本身正确（`pushed`=已推送、`testing`=验证中），
仅场景用错了断言期望值。

| # | 失败场景 | 父报告现象 | 实际状态 | 裁决依据 |
|---|---|---|---|---|
| 1 | `dispatch-single-flight-startup-prevention` | `.status-pill` 期望 `testing\|implemented\|verified\|done`，实际 `🚀 已推送` | `pushed`（已推送） | 场景用英文状态字面量；产品渲染中文 `🚀 已推送`。状态显示正确，场景断言期望值错误 |
| 5 | `state-writeback-protection-active-testing` | `.status-pill` 期望 `testing\|implemented\|verified\|done`，实际 `🔍 验证中` | `testing`（验证中） | 同上；产品正确显示「验证中」（= testing），场景期望英文 `testing` 字面量 |
| 7 | `verifier-reconciliation-pass-merged` | `.status-pill` 期望 `testing\|done\|verified`，实际 `🔍 验证中` | `testing` | 同上；产品「验证中」即 `testing`，场景期望值与产品 DOM 不符 |
| 9 | `verifier-reconciliation-fail-or-not-merged` | `.status-pill` 期望 `testing\|blocked\|done\|verified`，实际 `🔍 验证中` | `testing` | 同上 |

### B. 关键 UI 元素选择器错误（6 个场景）

场景断言的选择器在产品中不存在（产品实际 DOM 已在下表「产品实际 DOM」列列出），
Playwright `wait_for` 超时必然失败。产品对应功能（表格/详情/时间轴/活动流/配置页）均存在，
仅场景用错了选择器。

| # | 失败场景 | 场景断言的选择器 | 产品实际 DOM | 裁决依据 |
|---|---|---|---|---|
| 2 | `spec-overview-table-display` | `table` | 概览页为 `.cards-grid` + `.card`（`renderOverview`），**无 `<table>`**；项目页才有 `table.spec-table` | 场景导航 `#overview` 却断言 `table`——概览页无表格；产品按设计渲染项目卡片 |
| 3 | `dispatch-single-flight-concurrent-protection` | `.spec-detail`、`[class*='run-card']`（期望 1 个） | 详情页为 `.page-title` + `#tl-root` 时间轴（`renderTimeline`），**无 `.spec-detail`、无 `.run-card`** | 场景点击 spec 进入详情后断言不存在的容器类；运行记录以时间轴节点 + 弹窗呈现，非卡片列表 |
| 4 | `spec-detail-empty-state` | `.spec-detail` | 详情页无 `.spec-detail` 容器 | 同上；产品空状态以 `.empty-state` 呈现于页签内 |
| 6 | `activity-log-entry` | `.activity-list`、`.activity-item` | 运维页为 `.activity-timeline` + `.activity-card`（`renderActivities`），**无 `.activity-list`** | 场景导航 `#activities` 断言不存在的列表类 |
| 8 | `settings-page-load` | `.settings-panel` | 配置页为 `renderConfig`（`.config-*` / `.card`），**无 `.settings-panel`** | 场景导航 `#config` 断言不存在的面板类 |
| 10 | `spec-status-transition-flow` | `.status-history`、`.history-item` | 详情页**无状态历史组件**；状态转换以时间轴（`#tl-root`）呈现 | 场景断言不存在的状态历史组件 |

> 注：`[class*='run-card']` 在 `style.css` 中有样式定义但 `app.js` 不渲染（历史遗留样式），
> 产品以时间轴呈现运行记录——场景对「运行卡片」的存在与数量（期望 1）的断言在产品中无对应实体。
> 即便 mock 数据到达，`element_count` 也恒为 0（`run-card` 从不渲染），属场景构造缺陷。

### C. 与「运行卡片数量」相关的断言（并入 #3）

`dispatch-single-flight-concurrent-protection` 的 `element_count [class*='run-card'] expected=1 actual=0`
与 B 类同根因：产品无 `run-card` 渲染路径。该断言既不能证明也不否定单飞守卫的正确性——
单飞守卫是**后端调度**契约（一个 spec 只派发一个 implementer run），其正确性由
`tests/test_startup_double_dispatch.py` 的并发线程用例（`enqueue_calls == 1`）证明，
浏览器断言运行卡片数量无法观测该契约。

---

## 验证（本 SPEC 不引入代码变更）

- `python3 -m pytest tests/test_startup_double_dispatch.py -q` → **10 passed**（单飞守卫并发/顺序/清理、状态回写保护、verifier 对账全部覆盖）
- `python3 -m pytest tests/test_pm_verification.py tests/test_pm_dispatch.py -q` → **56 passed**（pm-engine 派发/验证核心无回归）
- `python3 -m pytest tests/ -q` → **947 passed, 1 failed**。唯一失败 `tests/test_v2_dev_server.py::TestAllocatePort::test_seq_offsets_within_range`
  与父 SPEC 无关：`allocate_port` 测试假设端口段全空闲，而本机 19001 端口被运行中的 dev-server 占用，
  `allocate_port` 正确跳过占用端口 → 断言 `19001 == 19000+1` 失败。属环境相关失败（端口占用），非产品缺陷。
- `npm run build`（v3 dashboard `max build`）→ 通过（见任务 2.1）
- `bash scripts/package.sh` → 生成 `dist/fenixd-20260902.tar.gz`（见任务 2.3）

## 建议（不在本 SPEC 范围）

父验证报告的 10 个伪失败暴露了**验证场景侧**两点可改进项，建议另立 SPEC 处理（非本 SPEC）：
1. 浏览器场景对 spec 状态断言应使用产品实际渲染的中文状态标签（`就绪/已实现/验证中/已验证/有Bug/完成/已推送`），
   而非英文状态机字面量；否则 `text_match` 对所有状态类断言恒失败。
2. 浏览器场景应使用产品实际 DOM 选择器（概览 `.cards-grid`、详情 `.page-title`/`#tl-root`、活动 `.activity-timeline`、
   配置 `renderConfig`），并避免断言后端调度契约（单飞/回写保护/对账）为浏览器可观测行为——
   此类契约应以其后端单元测试为准（已全部通过）。
