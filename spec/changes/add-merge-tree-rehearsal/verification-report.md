# 验证报告：add-merge-tree-rehearsal

> 本报告由 Fenix Planner Agent（裁决链 planner-judge）编写，内容为结构化验证产物（report.json / .fenix-run-result.json）的裁决结论 + 人类可读分析。

## 结论：✅ 通过（verified，无产品 Bug；6 个失败场景均为测试场景缺陷）

**状态：verified — 8 场景通过 2、失败 6、错误 0（0 个真实产品 Bug）**

本 SPEC 验证未发现产品 Bug。8 个场景中 2 个通过；6 个失败场景经逐个场景、逐断言归因（assertion_triage 共 10 条）**全部归类为 test-defect**（测试用例自身缺陷，非产品缺陷），已登记为断言级豁免清单。被测产品（merge-tree 预演相关 detail/list 渲染与交互）行为正确：零冲突正常流转、语义冲突直通 repair、repair 轮次上限兜底、产物冲突自愈、旧 git 回退熔断、repair 运行记录展开，六条核心语义在失败场景的其余功能断言中均被验证通过，且独立 Playwright 复现（相同 mock 数据 / 被测实例 127.0.0.1:55091 / 相同浏览器配置）全部渲染正常。

裁决依据 add-verdict-evidence-taxonomy（每个非 PASS 场景补 classification/evidence）与 add-interaction-contract-and-per-assert-triage（逐断言归因）；`core/verdict_check.validate_report` 校验通过（ok=True、violations=[]、classified=6），D3 状态映射已直接给对（test-defect → status=failed），无需框架强制改写。

| 指标 | 数量 |
| --- | --- |
| 通过 | 2 |
| 失败 | 6（全部为测试场景缺陷） |
| 错误 | 0 |
| 产品 Bug | 0 |

## 失败场景裁决摘要

六个失败场景可聚合为 3 类根因，均为测试设计缺陷：

### 1. 断言时序 / 首屏渲染延迟（4 个场景、共 5 条 first-layer 断言）

- **场景**：`rehearsal-zero-conflict-normal-flow` / `rehearsal-semantic-conflict-direct-repair` / `rehearsal-round-cap-fallback-re-dispatch` / `rehearsal-old-git-fallback-fp-circuit-breaker`
- **失败断言**：`element_visible [.ant-timeline-item]`（前三个场景各有 1 条 + R3 还有 `element_count [.ant-timeline-item:has-text('repair')]` expected=2/actual=0），均为第 1 层「元素可见/计数」。
- **根因**：verify 并行执行（并行度 5，首批 6 场景）时 dashboard SPA 首屏渲染耗时超出断言窗口——场景 wait(1200ms) 后立即执行 `element_visible`（轮询 3000ms），而首屏在并发下需要 4.2s~15s 才渲染完成。断言在渲染完成前取不到 `header/timeline` 节点；同场景第 3 层 `text_contains`/`no_console_error` 断言的轮询窗口更靠后，恰好在渲染完成后执行并全部通过，形成「同场景部分断言过、部分超时」的表象。
- **佐证**：
  - 独立复现（repro_timeline.py，相同 mock 数据 / 55091 实例 / `--disable-animations` 等全同配置）：单场景 6 个 `.ant-timeline-item` **全部 visible=True**，header「已验证」、时间轴文本正确。
  - 并行负载实验（repro_parallel.py 6 并发）：1.2s+3s 断言窗口内 **0 header / 0 timeline**（页面未渲染）；加长到 15s（repro_parallel2.py）：**6/6 完整渲染**，item_count=6、header「已验证」、内容正确。
  - 各场景其余功能断言全通过：R1 的「已验证」「状态转移」+ 无回退/无 repair/无 fp；R2 的「实现中」「repair」「running」+ 无回退/无阻塞/无 fp；R3 的「实现中」「运行记录」「回退」+ alert 信息条；R4 的「阻塞」「Circuit breaker tripped」「fp=3cf770823ad5」×2 + `element_count 状态回退=2`。产品在这些场景中渲染的正是 mock 数据声明的语义。
- **修复方向**：加大场景首屏等待（wait ≥ 8s）或对渲染完成设置稳定锚点断言（先等 `.ant-page-header-heading-title` 再断言时间轴），避免 first-layer 断言与渲染竞态。

### 2. `:has-text('repair')` 选择器语义错误（1 个场景、1 条断言）

- **场景**：`rehearsal-artifact-conflict-self-heal`
- **失败断言**：`element_not_exist [.ant-timeline-item:has-text('repair')]` expected=0 / actual=1。
- **根因**：测试本意断言「产物冲突自愈路径不派发 repair **运行节点**」，但用了文本子串匹配，实际命中 **implementer run 节点的 markdown summary**：「…真合并后产物自愈完成，**无需 repair**」（summary 由产品按设计渲染）。repro 实测匹配项文本为 `2026-09-04 16:05:00 开发 Agent claude-sonnet-5@gateway ok 耗时 30分 merge-back 预演检出产物冲突（build/、node_modules/）…`——正是 implementer 节点。
- **佐证**：同场景 `text_contains「已验证」「自愈」`、`element_not_exist「状态回退」`、`no_console_error` 全部通过；产品实际只渲染 implementer + verifier 两个 run 节点，**无 repair agent_type 运行节点**，R3「产物冲突放行现行自愈、不派发 repair」语义正确。
- **修复方向**：断言应锚定 repair **运行节点**本身（如 `agent 标签 == repair` 或状态标签），或将 `:has-text('repair')` 限定在节点标题区，排除 summary 正文。

### 3. antd 6 Collapse 展开面板类名变更导致选择器失效（1 个场景、3 条断言）

- **场景**：`rehearsal-repair-run-record-interaction`
- **失败断言**：`element_visible [.ant-collapse-content-active]`、`text_contains [.ant-collapse-content-active] 「语义冲突已解决」/「main 合入实现分支」`。
- **根因**：被测产品已升级 **antd 6.6.0**，Collapse 展开面板类名由 antd 5 的 `.ant-collapse-content-active` 改为 `.ant-collapse-panel-active`（item 上同时置 `.ant-collapse-item-active`）。场景选择器基于 antd 5 DOM 编写，在 antd 6 下匹配不到任何元素。
- **佐证**：Playwright 实测（repro_interact.py / repro_interact4.py）点击 `.ant-timeline-item:has-text('repair') .ant-collapse-header` 后 **Collapse 实际展开成功**（`aria-expanded=true`、`.ant-collapse-panel-active` 出现），`getRunTail('/api/runs/repair-rehearsal-conflict-demo-…')` 加载的 mock 事件流完整渲染——页面 innerText 中含「我将把 main 合入实现分支并解决语义冲突 src/conflict.go」（body count=37）与「merge 完成，语义冲突已解决」（body count=35）。`no_click_interception`（点击不被遮挡）与 `no_console_error` 通过。repair 通道派发留痕可追溯，产品功能正常。
- **修复方向**：断言选择器适配 antd 6——展开态用 `.ant-collapse-panel-active`（或 `.ant-collapse-item-active`），事件文本断言改在 `.ant-collapse-body` 内查询。

## 场景结果

| 场景 | 状态 | 失败断言 | 分类 | 根因 |
| --- | --- | --- | --- | --- |
| rehearsal-zero-conflict-normal-flow | failed | 1/7 | test-defect | 断言时序/首屏渲染延迟 |
| rehearsal-semantic-conflict-direct-repair | failed | 1/8 | test-defect | 断言时序/首屏渲染延迟 |
| rehearsal-round-cap-fallback-re-dispatch | failed | 2/8 | test-defect | 断言时序/首屏渲染延迟（含 element_count 同窗口失败） |
| rehearsal-artifact-conflict-self-heal | failed | 2/6 | test-defect | 渲染延迟 + `:has-text('repair')` 误匹配 summary |
| rehearsal-old-git-fallback-fp-circuit-breaker | failed | 1/8 | test-defect | 断言时序/首屏渲染延迟 |
| rehearsal-repair-run-record-interaction | failed | 3/5 | test-defect | antd 6 Collapse 类名选择器失效 |
| rehearsal-empty-timeline | pass | 0/5 | - | - |
| rehearsal-semantic-conflict-list-no-ready-degradation | pass | 0/7 | - | - |

## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷。

| 场景 | 断言 | 分类 | 豁免理由 |
| --- | --- | --- | --- |
| rehearsal-zero-conflict-normal-flow | element_visible `.ant-timeline-item` | test-defect | 并行负载下渲染延迟超断言窗口；同场景功能断言全通过；独立复现 6/6 可见 |
| rehearsal-semantic-conflict-direct-repair | element_visible `.ant-timeline-item` | test-defect | 同上（R2 直通 repair 节点渲染经 text_contains「repair」「running」验证） |
| rehearsal-round-cap-fallback-re-dispatch | element_visible `.ant-timeline-item` | test-defect | 同上 |
| rehearsal-round-cap-fallback-re-dispatch | element_count `.ant-timeline-item:has-text('repair')`=2 | test-defect | 同窗口渲染未完成 count=0；后续「回退」「运行记录」断言通过证明 2 轮 repair 展示正确 |
| rehearsal-artifact-conflict-self-heal | element_visible `.ant-timeline-item` | test-defect | 同渲染延迟；「已验证」「自愈」断言通过 |
| rehearsal-artifact-conflict-self-heal | element_not_exist `.ant-timeline-item:has-text('repair')` | test-defect | `:has-text` 误匹配 implementer summary 中「无需 repair」；产品实际无 repair 运行节点（repro 佐证） |
| rehearsal-old-git-fallback-fp-circuit-breaker | element_visible `.ant-timeline-item` | test-defect | 同渲染延迟；熔断语义 7 项断言全通过（阻塞/Circuit breaker/fp/2 次回退） |
| rehearsal-repair-run-record-interaction | element_visible `.ant-collapse-content-active` | test-defect | antd 6 类名变更（→ `.ant-collapse-panel-active`）；点击后 Collapse 实际展开 |
| rehearsal-repair-run-record-interaction | text_contains（语义冲突已解决） | test-defect | 文本已渲染于 `.ant-collapse-body`，断言作用域选择器失效 |
| rehearsal-repair-run-record-interaction | text_contains（main 合入实现分支） | test-defect | 文本已渲染于 `.ant-collapse-body`，断言作用域选择器失效 |

## 验证方法说明

本次裁决前进行了三类独立复现取证（脚本位于 /tmp）：
- **repro_timeline.py**：R1/R2 同款 mock + 被测实例 55091 + harness 同款浏览器参数（`--disable-animations` / reduced-motion / 1280×800），单场景 6 个 `.ant-timeline-item` 全部可见、header 与时间轴文本正确——证明产品渲染正常。
- **repro_parallel.py / repro_parallel2.py**：6 并发复现 harness 负载，断言窗口内 0 渲染、15s 后 6/6 完整渲染——证明失败源于并行负载下的渲染时序。
- **repro_artifact.py / repro_interact.py / repro_interact3.py / repro_interact4.py**：确认 `:has-text('repair')` 命中 implementer summary；确认 antd 6 Collapse 展开面板类名 `.ant-collapse-panel-active`、repair 事件流文本完整渲染。

结论：**未发现产品 Bug**。6 个失败场景均为测试场景缺陷，修复测试场景（首屏等待加长/稳定锚点、`:has-text` 锚定修复、antd 6 选择器适配）后应复验，以把 R1-R4 六条核心语义的端到端验证从「豁免」提升为「全断言通过」。

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

