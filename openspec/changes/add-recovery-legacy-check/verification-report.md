# 验证报告：add-recovery-legacy-check

- **验证时间**：2026-08-30T04:41:01+00:00
- **总体结论**：✅ **验证通过（verified）**
- **结果统计**：11 个场景，11 通过，0 警告，0 失败，0 错误，0 环境阻塞
- **断言统计**：共 49 项断言（第 1/2 层 22 项、第 3 层 23 项、第 4 层 1 项），全部通过
- **Bug 数量**：0

## 一、总览

本次验证针对「死亡 run 遗产保留 / 恢复重派」变更，通过 mock API 驱动 Fenix Dashboard v2（AMIS），覆盖恢复链路的用户可见面、诊断面、交互面与回归面。全部场景一次通过，未发现产品 Bug。

## 二、场景结果明细

| # | 场景 ID | 类型 | 结果 | 覆盖点 |
|---|---------|------|------|--------|
| 1 | recovery-redispatch-list-row | 正向路径 | ✅ 通过 | 恢复重派后列表行渲染，SPEC 名与「就绪」徽标正常，行操作下拉未被遮挡 |
| 2 | recovery-error-detail-dialog | 正向路径 | ✅ 通过 | 详情对话框完整展示「Auto-recovered from stuck implementing (35 min)」，清除错误按钮可见 |
| 3 | recovery-error-clear-online | 交互流程 | ✅ 通过 | 在线清除恢复错误：对话框关闭、列表行保留（清除不删 SPEC） |
| 4 | recovery-timeline-backtrack-node | 中间状态 | ✅ 通过 | 时间轴 3 节点（派发→死亡 run→回退），死亡/回退时间戳正确 |
| 5 | recovery-run-record-modal | 交互流程 | ✅ 通过 | 死亡 run 记录弹窗呈现，标题含 run_id，事件流区域已渲染 |
| 6 | no-legacy-first-run-zero-impact | 回归点 | ✅ 通过 | 无遗产首次 run 零影响：「实现中」徽标正常，无「RECOVERY LEGACY / 遗产检查」专设 UI 残留 |
| 7 | overview-recovery-problem-count | 回归点 | ✅ 通过 | 概览「问题数」tile = 1，恢复重派现场在概览层不被吞掉 |
| 8 | activities-empty-state | 空状态 | ✅ 通过 | 运维记录页空态：标题与「全部」页签正常，时间轴节点数 0，无骨架残留或报错 |
| 9 | recovery-error-special-chars | 异常路径 | ✅ 通过 | 超长特殊字符 error（引号/管道/换行）pre-wrap 完整换行渲染，无横向溢出 |
| 10 | recovery-spec-keyword-search | 交互流程 | ✅ 通过 | 关键词过滤可检索到恢复重派 spec；输入不存在名称后行从 DOM 消失 |
| 11 | successor-merged-status-advanced | 回归点 | ✅ 通过 | 后继 run 成功 merge 后状态推进为「已验证」，收编产出照常走验证链 |

## 三、逐场景要点

### 1. recovery-redispatch-list-row（正向路径）
恢复链路把 spec 重置为 ready 并写入 Auto-recovered 错误文本后，`/api/specs` 列表以「就绪」徽标行呈现。第 1/2/3 层断言（行可见、SPEC 名、徽标文本、下拉按钮无遮挡）全部通过。

### 2. recovery-error-detail-dialog（正向路径）
行操作下拉打开「详情」对话框后，STATE error 字段（`Auto-recovered from stuck implementing (35 min)`）以 pre 块完整展示，且因 error 存在「清除错误」按钮可见。文本逐字节匹配。

### 3. recovery-error-clear-online（交互流程）
点击「清除错误」→ 关闭对话框后：对话框已从 DOM 移除（count=0）、列表行仍在、SPEC 名保留——确认清除错误不删除 SPEC，恢复重派态下既有清除能力仍可用。

### 4. recovery-timeline-backtrack-node（中间状态）
详情页时间轴渲染 3 个节点（派发、死亡 run 记录、回退），死亡 run 与回退节点的时间戳（`2026-08-30T01:10:00Z` / `2026-08-30T02:30:00Z`）均正确。按冒烟预检结论，当前 AMIS 版本时间轴 title/detail 渲染为空串，故本场景只断言节点数与时间戳，状态转换与 reason 原文由场景 2 承担——这是场景设计上的已知取舍，非产品缺陷。

### 5. recovery-run-record-modal（交互流程）
点击时间轴死亡 run 节点后弹出运行记录弹窗：`.dark-Modal` 可见、标题含「运行记录」与 run_id（`impl-legacy-recheck-1-a1`）、run 事件流区域（`.rs-stream`）已渲染。用户可据此定位遗产来源 run。

### 6. no-legacy-first-run-zero-impact（回归点）
无遗产的首次实现 spec 正常渲染「实现中」徽标，页面无「RECOVERY LEGACY」「遗产检查」残留（element_not_exist 通过）——确认遗产注入为空串时对既有 UI 零影响。

### 7. overview-recovery-problem-count（回归点）
概览页「问题数」tile 显示 1（`.v2-stat-num` 第 4 个 tile 精确匹配），项目卡片含 `legacy-sandbox` 与「问题: 1」——带 error 的恢复重派 spec 正确计入 problems 聚合。

### 8. activities-empty-state（空状态）
无 Administrator 处置记录时，运维记录页标题、「全部」页签照常渲染，时间轴节点数为 0，无骨架残留或 console 报错。

### 9. recovery-error-special-chars（异常路径）
模拟网关瞬时故障场景（`provider circuit open: gpt-x-gateway (HTTP 502 x3)`、含「网关瞬时故障」等引号/管道/括号/换行文本）：详情对话框完整渲染，`no_overflow` 断言通过（scroll_width=client_width=1280，scroll_height=client_height=800，无横向/纵向溢出）。

### 10. recovery-spec-keyword-search（交互流程）
搜索框输入 `legacy-recheck` 可过滤保留目标行；输入 `no-such-spec-xyz` 后该行从 DOM 消失（count=0），搜索框本身仍可用——恢复重派 spec 可被检索定位，过滤流程未被破坏。

### 11. successor-merged-status-advanced（回归点）
后继 run 成功 merge（consume_legacy 回收遗产）后，spec 状态沿既有状态机推进为 verified，列表行呈现「已验证」成功徽标——收编产出不豁免验证链。

## 四、特判规则核查

- **no_console_error**：11 个场景的 console 断言均无错误、无需 `filtered_network` 豁免，全部真实通过。
- **no_auth_error / 网络可达性**：本验证为本地 mock 驱动，未涉及真实云端端点，无签名/密钥类错误，也无网络不可达情况。
- **断言时序**：未出现「弹窗关闭后查询弹窗内元素」的时序性失败；场景 3 在关闭前完成清除、关闭后仅断言持久 DOM，设计正确。
- **视觉对比（第 4 层）**：所有场景均为首次运行，自动建立基线（`baseline_created`），无 SSIM 对比项；场景 9 的溢出检查在预期视口（1280×800）内通过。

## 五、结论

`add-recovery-legacy-check` 的仪表盘验证面**全部通过，判定为 verified，无待修复 Bug**。恢复重派状态呈现、错误诊断与在线清除、时间轴生命线、死亡 run 记录可查、概览聚合、空态、异常文本布局、检索过滤及后继 run 状态推进等能力均按 SPEC 预期工作；无遗产场景对既有 UI 零影响。

> 备注：遗产保留机制本身（worktree/分支保留、legacy 上下文注入 implementer prompt、consume_legacy 回收）位于 daemon 内部，由单测覆盖（tasks 3.x）；本次浏览器验证聚焦其用户可见面，符合场景设计意图。
