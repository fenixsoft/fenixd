# 验证报告：fix-improve-run-lifecycle-governance

## 验证结果

- **状态**: bug-found
- **总场景数**: 17
- **通过**: 2
- **失败**: 15
- **通过率**: 11.8%

## 严重 Bug（Critical）

### 系统性缺陷：Dashboard 未渲染治理 SPEC 行

**影响范围**: 12 个场景（占所有失败场景的 80%）

**症状**:
所有包含 `governance-*` 测试数据的场景均失败，错误信息一致：
```
Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator("tr.spec-row:has-text(\"governance-*\")").first to be visible
```

**受影响场景**:
1. recovery-deferred-live-child-stays-ready
2. worktree-lock-rebuild-and-stale-release
3. dispatch-lock-conflict-enters-backoff
4. post-recovery-followup-finds-stuck-ready
5. patrol-no-inprogress-but-fake-ready-stall
6. regression-active-run-not-misjudged
7. recovery-no-live-child-resets-normally
8. backoff-exhausted-raises-dispatch-stalled
9. liveness-judge-unavailable-failsafe-kill
10. liveness-advancing-extends-deadline
11. post-recovery-followup-confirmed-recovered
12. extension-budget-exhausted-hard-kill
13. timeout-supervision-disabled-wall-clock

**根因分析**:
Mock API 响应（`/api/specs?project=fenixd`）未包含治理测试 SPEC 数据，导致 dashboard 渲染层无可渲染内容。所有依赖这些 SPEC 行的断言（子行可见性、文本内容）全部失败。

**证据**:
- 所有12个失败场景的断言错误模式完全相同
- 同一选择器在 `smoke-dashboard-serves-8787` 场景通过（证明选择器本身有效）
- Dashboard 渲染逻辑健康（`no_console_error` 全部通过）

## 次要 Bug（Minor）

### 1. 空状态测试选择器错误

**场景**: empty-state-no-specs-no-alerts

**症状**:
```
element_not_exist tr.spec-row:has-text("") 
expected: 0
actual: 62
```

**根因**: 测试场景设计缺陷，使用 `tr.spec-row:has-text("")` 验证空状态，但实际匹配到 62 行真实 SPEC 数据。

### 2. 活动卡片计数异常

**场景**: patrol-cooldown-dedup-no-repeat-signal

**症状**:
```
element_count .activity-card
expected: 1
actual: 0
```

**根因**: 运维记录活动卡片未渲染，可能与治理 SPEC 渲染问题相关。

## 通过场景验证

以下2个场景通过，证明 dashboard 基础功能正常：

1. **smoke-dashboard-serves-8787** - Dashboard 端口8787正常提供服务
2. **timeout-liveness-judge-active-run-survives** - 活跃 Agent 运行统计正常

## 视觉对比结果

所有失败场景的 SSIM 值均低于阈值（0.85-0.77），表明当前实现与基线存在显著差异。

## 结论

**验证未通过**。发现1个严重系统性缺陷：Dashboard 未渲染治理相关的 SPEC 行，导致12个场景失败。另有2个小问题。

**根本原因**: Mock API 响应未包含治理测试 SPEC 数据，属于验证基础设施问题，而非 fenixd 产品代码缺陷。
