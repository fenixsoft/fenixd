# 验证报告 · fix-fix-fix-improve-failover-model-mapping-ui

> 判定：**通过（done）**
> 原始验证引擎执行时间：2026-08-28T18:36Z（23 场景：16 通过 / 7 失败）
> Administrator 复核裁定：2026-08-29（本文件为重建版——judge 原报告写入了已被清理的
> worktree `impl-fix-fix-fix-improve-failover-model-mapping-ui-1787942194`，主树缺失）

## 结论

原判 bug-found（1 真实 Bug + 6 测试预期错误）经代码级复核**全部不成立**，7 个失败均为
验证基础设施/场景缺陷。修正后由验证引擎实测（`report-admin-infra-check.json`）：
**7/7 通过，0 条断言失败**。本 SPEC 修复的 BUG-01（`renderAgentAssignment` provider
形态归一化）经 23 场景全量复验确认有效（`chain-load-str-form` 等原失败场景全部转通过）。

## 7 个失败的逐项复核

### ×6 · element_count「expected=1 / actual=2」——引擎字段错位（框架缺陷，非场景笔误）

影响：`chain-load-echo-mixed`、`chain-load-str-list`、`chain-load-mixed-partial-model`、
`chain-move-buttons-disabled`、`chain-existing-array-not-overwritten`、`chain-list-operations-save-order`。

- 各场景按行（`nth-child(1)`/`nth-child(2)`）断言**全部通过**、场景描述明写两行——产品渲染正确。
- 真根因：`verify_engine/assertions.py` 的 `_assert_element_count` 只读 `expected` 字段
  （缺省回退 1），而 planner 生成的事实约定是 `count` 字段（全库 test_scenarios.json
  133 处 `count` vs 28 处 `expected`）。所有 `count: 2` 被静默按 1 断言 → 系统性伪失败。
- **此缺陷是本 fix 族谱两轮验证反复翻车的共同根因**（上一轮 judge 亦将同模式判为
  「测试剧本笔误」）。
- 修复：引擎改为 `count` 优先、`expected` 兼容、缺省 1（admin 提交）。

### ×1 · chain-empty-provider-row-dropped-on-save——伪 Bug（判定者根因认定与代码事实相反）

- 判定者声称根因为「`collectConfigData` 未过滤空 provider 行」。**代码事实相反**：
  空行过滤自初始提交 55f7572 即存在（app.js `// 仅收集已选 provider 的行（空行视为未配置，丢弃） if (provider)`）。
- 同场景 `text_contains「已保存」` 与 `element_enabled` 均通过——保存成功、空行确被丢弃。
- 失败断言 4/5（`assign-fields disabled`、无残留 `.chain-row`）要求「保存后重绘恢复空状态」，
  与产品**刻意设计**矛盾：保存后走 `refreshConfigDataSilently` 仅更新数据快照、不重绘表单 DOM
  （app.js:2439-2461 注释明确：防 morphdom 重绘吞掉保存横幅——那正是此前 6 例伪失败的根因）。
- 失败断言 1（`#config-save-banner.success` 3s 超时）为时序竞态：保存后 1500ms 步骤等待 +
  3s 断言窗口 > 4s 横幅自动隐藏寿命。
- 场景修正：移除两条重绘断言、描述改为符合静默刷新设计、post-save 等待 1500→300ms。

### 附带修正 · chain-list-operations-save-order 选行错误

上移 b 后链序为 [b, a, c]，a 位于第 2 行；原步骤删 `nth-child(3)` 删掉的是 c。
已改为删 `nth-child(2)` 并补保存后 300ms 等待。修正后实测行序 [b, c] 断言通过。

## 实证

`.fenix/verify-progress/fix-fix-fix-improve-failover-model-mapping-ui/report-admin-infra-check.json`
（admin 复核运行，7 场景全通过、0 条断言失败；warning 状态仅为与上一轮截图的视觉基线噪声差异）。
