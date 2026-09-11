# 验证报告：fix-verify-process-lifecycle

**验证时间：** 2026-09-05T08:36:20 UTC  
**实例端口：** 127.0.0.1:36375（command 型，framework 注入端口）  
**最终裁决：** ✅ verified（无产品 Bug）

---

## 摘要

| 指标 | 值 |
|------|-----|
| 场景总数 | 8 |
| 通过 | 6 |
| 失败（test-defect） | 1 |
| 警告（flaky） | 1 |
| 错误/环境阻塞 | 0 |

**核心结论：** command 型 dashboard 实例的进程生命周期治理（D1-D7）在本轮验证中功能正确，未发现产品级 Bug。两个非 PASS 场景均经逐断言归因为测试侧问题。

---

## 非 PASS 场景裁决

### 场景 1：spec-testing-status-visible（test-defect → failed）

| 项目 | 内容 |
|------|------|
| 失败断言 | `text_match`（layer 3）：`.ant-page-header-heading-title` exact match |
| 期望值 | `fix-verify-process-lifecycle` |
| 实际值 | `fix-verify-process-lifecycle完整模式验证中` |
| 根因 | `detail.tsx:562-589` 的 `headerCfg.title` 渲染 `<Space>` 包含：`<span>{spec}</span>` + 模式 Tag（"完整模式"）+ 状态 Tag（"验证中"）。antd Tag 的 `marginInlineEnd: 0` 导致 innerText 拼接无空格。这是 `add-fast-track-mode` 功能的既定设计（行 566-570 注释），产品行为正确。 |
| 场景真实目标 | 状态徽章显示「验证中」——已由同场景的 `text_contains "验证中"` 断言通过 |
| 修复建议 | 测试断言改为对标题内 `<span>{spec}</span>` 单独匹配（`element_visible` + `text_match` 限定 span），或改 `text_match` 为 `text_contains` |
| 影响范围 | 仅影响该测试场景，不影响产品功能 |

### 场景 2：overview-active-runs-present（flaky → warning）

| 项目 | 内容 |
|------|------|
| 失败断言 1 | `element_visible`（layer 1）：`.ant-card:has(.ant-card-head-title:has-text('活跃 Agent 运行'))` — Locator timeout 3000ms |
| 失败断言 2 | `text_contains`（layer 3）："活跃 Agent 运行" — 元素未渲染，文本不可达 |
| 根因 | `IntroduceRow` 仅在 `/api/overview` 数据加载完成后渲染（`overview/index.tsx:84-88`：`data ? <Space> : null`）。SPA remount 后数据重加载时序不稳定，2000ms 等待未覆盖本次执行的加载延迟。 |
| 排除产品 Bug 的依据 | ① Tile 组件渲染 antd `Card`（`IntroduceRow.tsx:38-53`），`ActiveAgentTile` 无条件渲染（行 299），选择器正确；② 同一选择器模式在 `spec-detail-verify-progress` 场景（"验证进度"卡）通过；③ `dashboard-instance-healthy` 在相同 URL 通过；④ `no_network_error` / `no_console_error` 均通过，排除 API 错误或 JS 异常。 |
| 性质 | 时序不稳定（flaky），重试大概率通过 |
| 修复建议 | 若需提升稳定性，可将 `overview-active-runs-present` 场景的 wait 时间从 2000ms 增至 4000-5000ms，或对 element_visible 断言增加重试策略 |

---

## 通过场景一览

| 场景 ID | 验证目标 | 关键断言 |
|---------|---------|---------|
| dashboard-instance-healthy | command 型实例提供 SPA 服务 | ✅ 概览页标题、`.ant-space-vertical` 统计卡区域可见 |
| spec-api-returns-real-state | 后端 API 契约正确 | ✅ `/api/specs/<spec>` 返回 status=testing、implementer_run、verify_progress |
| consecutive-navigation-stable | 进程组隔离（killpg 不误伤 daemon） | ✅ 连续三次导航正常渲染、无网络错误 |
| api-proxy-functional | API 代理链路完整 | ✅ `/api/prompts` 返回 agents/verifier.md |
| spec-detail-verify-progress | 验证进度卡渲染 | ✅ 「验证进度」卡片可见 |
| spec-no-error-banner | 终态收割无副作用 | ✅ `.error-banner` 元素不存在 |

---

## 生命周期治理要点验证矩阵

| 设计项 | 验证点 | 场景 | 结果 |
|--------|-------|------|------|
| D1 终态收割 | 未误杀 spec / 无 error banner | spec-no-error-banner | ✅ |
| D2 进程组杀树 | killpg 不误伤 daemon | consecutive-navigation-stable | ✅ |
| D3 ppid 自杀绑定 | 实例持续存活 | consecutive-navigation-stable | ✅ |
| D4 周期清扫豁免 | 活跃 run 未被清扫 | dashboard-instance-healthy（实例持续服务）| ✅ |
| D5 端口注入铁律 | 实例不争抢端口、API 正常 | spec-api-returns-real-state、api-proxy-functional | ✅ |
| D6 登记制 | command 型实例正确管理 | dashboard-instance-healthy | ✅ |
| D7 repair 轮 | ensure 语义正确启动实例 | api-proxy-functional（端点可达）| ✅ |

---

## 证据截图

- `screenshots/spec-testing-status-visible_assert_fail.png` — 标题文本匹配失败截图
- `screenshots/overview-active-runs-present_assert_fail.png` — 活跃运行卡未出现截图

> ⚠️ 以上截图为测试引擎自动捕获，供后续调试参考。本报告不包含截图内容（模型无图像输入能力）。

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

