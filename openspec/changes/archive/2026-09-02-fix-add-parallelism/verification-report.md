# 验证报告：fix-add-parallelism

**验证日期**：2026-08-24
**验证结论**：✅ VERIFIED — 所有场景通过

## 概述

本报告验证 `fix-add-parallelism` SPEC 修复效果：修复严格优先级调度器中「高优先级任务等待时，低优先级运行档继续补齐并行度」的真实产品缺陷。

## 测试环境

- **项目**：fenixd（/root/fenixd）
- **Dashboard**：Python 标准库 HTTP 服务，端口 8787
- **浏览器测试**：playwright-cli（Chromium）
- **单元测试**：pytest，27 个调度/并行相关用例

---

## priority-parallel-scheduler SPEC

### Requirement: 高优先级任务先执行

#### Scenario: 高低优先级同时就绪时高优先级先派发
**测试**：`TestPriorityScheduler::test_high_priority_dispatches_first`
**结果**：✅ PASS
P1 的 spec-a 先于 P5 的 spec-b 被派发，且因跨档不并行，P5 不启动。

#### Scenario: 高优先级到达时不抢占正在运行的低优先级
**测试**：`TestPriorityScheduler::test_high_priority_no_preempt`
**结果**：✅ PASS
P5 正在运行时 P1 到达：已运行的 P5 不被终止；且期间不派发新的 P5 同档任务（这是本 SPEC 修复的核心 bug）。

### Requirement: 同一优先级任务可并行执行

#### Scenario: 并行度 2 时同优先级任务并行运行
**测试**：`TestPriorityScheduler::test_same_priority_parallel`
**结果**：✅ PASS
三个 P3 就绪 + 并行度 2 → 同时派发 2 个，第 3 个留队。

#### Scenario: 并行度上限不被突破
**测试**：`TestPriorityScheduler::test_max_concurrent_not_exceeded`
**结果**：✅ PASS
5 个同优先级就绪任务 + 并行度 2 → 活跃运行数恒为 2。

### Requirement: 不同优先级任务不并行

#### Scenario: 槽位空闲但存在运行中的不同优先级任务时不派发
**测试**：`TestPriorityScheduler::test_different_priority_no_parallel`
**结果**：✅ PASS
P1 正在运行（1槽），P5 就绪 → 空闲槽位不被 P5 占用。

#### Scenario: 同档任务在运行期间允许补齐并行度
**测试**：`TestPriorityScheduler::test_same_bucket_fills_idle_slot`
**结果**：✅ PASS
P2 正在运行（1槽），另一个 P2 就绪 → 同档补齐，第二 P2 被派发。

### Requirement: verifier 紧随其 implementer 派发

#### Scenario: implementer 完成后 verifier 同档紧随
**测试**：`TestPriorityScheduler::test_verifier_immediately_after_implementer_same_bucket`
**结果**：✅ PASS
verifier 通过 `_enqueue_front` 入队，在同 priority 档内最先被派发。

### Requirement: 向后兼容

#### Scenario: 全部同优先级时按入队顺序并行
**测试**：`TestPriorityScheduler::test_all_same_priority_fifo_parallel`
**结果**：✅ PASS
全部 priority=5 时，按入队顺序 1→2→3 派发，并行度 2。

---

## parallelism-config SPEC

### Requirement: 并行度配置项

#### Scenario: 配置并行度为 4 被正确加载
**测试**：`TestDashboardParallelismConfig::test_write_max_concurrent_roundtrip` + UI 验证
**结果**：✅ PASS
Dashboard 配置页显示当前 `agents.max_concurrent = 2`；修改为 4 后保存，配置文件正确写入。

#### Scenario: 非法并行度校验失败
**测试**：`TestDashboardParallelismConfig::test_write_invalid_max_concurrent_rejected` + API 验证
**结果**：✅ PASS
提交 0、负数、非数字字符串均返回 400，配置文件不变。

#### Scenario: 未配置时使用默认值 2
**测试**：`TestDashboardParallelismConfig::test_max_concurrent_default_when_missing`
**结果**：✅ PASS
配置文件缺失 `max_concurrent` 时默认取 2。

### Requirement: Dashboard 可视化编辑并行度

#### Scenario: 配置页读取当前并行度
**测试**：浏览器 UI + API (`GET /api/config?project=fenixd`)
**结果**：✅ PASS
返回 JSON 包含 `agents.max_concurrent: 2`，UI 数字输入框正确显示。

#### Scenario: 修改并行度并保存，其它 agents 子键保持不变
**测试**：浏览器 UI 操作 + 配置文件校验
**证据**：`screenshots/03-parallelism-saved-4.png`
**结果**：✅ PASS
从 2 改为 4 保存后，`agents.subagent_model`、`max_retries`、`max_turns` 等子键保持原值不变。

#### Scenario: 提交非法并行度被拒绝且不写盘
**测试**：浏览器 UI 提交 0 + API 提交 -1/"abc"
**证据**：`screenshots/04-invalid-parallelism-rejected.png`
**结果**：✅ PASS
POST 返回 400 与错误说明，配置文件内容保持不变。

---

## 核心 Bug 修复验证

**Bug 描述**：严格优先级调度中，当高优先级任务在队列中等待时，正在运行的低优先级档会继续用就绪的低优先级任务补齐并行度，导致高优先级任务被不必要地延迟。

**修复后行为**：
- P5 正在运行 1 个（占用 1/2 槽位）
- P1 任务就绪入队（高优先级等待）
- 另一个 P5 任务就绪入队

**预期**：不派发任何新任务。运行档保持 P5 的 1 个继续运行（不抢占），但空闲槽位不被新的 P5 任务占用（避免高优先级被进一步延迟）。

**实际**：✅ 符合预期。派发任务数 = 0，活跃运行数保持 1，P5 和 P1 均留在队列中等待当前 P5 完成。

**验证方式**：
1. 单元测试 `test_high_priority_no_preempt` 通过
2. 独立脚本直接调用 `_process_queue` 验证通过

---

## 端到端多档位测试

**测试**：`test_e2e_priority_tiers_serial_and_parallel`
**场景**：并行度 2，P1 有 3 个任务，P5 有 2 个任务
**期望顺序**：
1. 先派发 P1-a、P1-b（并行度满）
2. P1-a 完成 → 派发 P1-c（同档补齐）
3. P1 全部排空 → 派发 P5-x、P5-y

**结果**：✅ PASS

---

## 边缘情况测试

| 边缘用例 | 结果 |
|---------|------|
| 负数并行度 (-1) | ✅ 400 拒绝 |
| 字符串并行度 ("abc") | ✅ 400 拒绝 |
| 大值并行度 (100) | ✅ 接受 |
| SPEC 无 priority 字段 | ✅ 默认 5 处理 |
| 状态不合法的队列条目 | ✅ 跳过，不影响调度 |
| 并发调度调用（线程安全） | ✅ `test_e2e_concurrent_process_queue_thread_safe` 通过 |

---

## 单元测试汇总

```
tests/test_core.py::TestPriorityScheduler  11 个 — 全部 PASSED
tests/test_core.py::TestDashboardParallelismConfig  6 个 — 全部 PASSED
其它调度相关  10 个 — 全部 PASSED
合计: 27 passed
```

总计 142 个测试中 141 通过，1 个失败（`test_stderr_no_fallback_parseable`，与本 SPEC 无关的流式解析测试）。

---

## UI 截图

| 截图 | 说明 |
|------|------|
| `screenshots/01-project-detail.png` | Fenix 项目详情页 |
| `screenshots/02-config-page.png` | 配置页，含并行度设置（默认 2） |
| `screenshots/03-parallelism-saved-4.png` | 并行度改为 4 保存成功 |
| `screenshots/04-invalid-parallelism-rejected.png` | 非法值 0 被拒绝 |

---

## 结论

**所有场景通过。核心 bug（高优先级等待时低优先级档补齐并行度）已修复。**

```json
{
  "status": "verified",
  "spec": "fix-add-parallelism",
  "bugs": [],
  "scenarios_total": 12,
  "scenarios_passed": 12,
  "unit_tests": {
    "scheduler_related": 27,
    "passed": 27
  }
}
```
