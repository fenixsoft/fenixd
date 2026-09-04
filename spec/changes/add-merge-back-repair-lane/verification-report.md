# 验证报告：add-merge-back-repair-lane

> 本报告由 Fenix Planner Agent（裁决链 planner-judge）编写，内容为结构化验证产物（report.json / .fenix-run-result.json）的裁决结论 + 人类可读分析。

## 结论：✅ 通过（verified）

**状态：verified — 6/9 场景通过，3 失败，0 错误（0 个真实产品 Bug）**

本 SPEC 验证未发现产品 Bug。9 个场景中 6 个通过；3 个失败场景经逐断言归因（assertion_triage，共 4 条失败断言）全部归类为 **test-defect**（测试用例自身缺陷，非产品缺陷），已登记为断言级豁免清单。被测产品（dashboard 渲染引擎 / 时间轴 / 列表展开行）行为正确：blocked 状态展示、概览计数、状态筛选、详情页状态标签、时间轴状态转移、error 清除按钮共 6 个核心场景全部 PASS。

裁决依据 add-verdict-evidence-taxonomy（每个非 PASS 场景补 classification/evidence）与 add-interaction-contract-and-per-assert-triage（逐断言归因）；`core/verdict_check.validate_report` 校验通过（violations=[]），D3 状态映射已直接给对（test-defect → status=failed），无需框架强制改写。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 3 |
| 错误 | 0 |
| 产品 Bug | 0 |

## 失败场景裁决摘要

三个失败场景均为测试用例设计缺陷，产品行为正确：

### 1. repair-run-in-detail-timeline（test-defect）

- **断言**：`text_contains [.ant-timeline-item]` 包含文本 `repair-repair-spec-1756905600`（repair run_id）——失败。
- **根因**：产品时间轴 run 节点按设计渲染 agent 标签 + 状态 done + 摘要 +「查看运行记录」折叠面板，raw run_id 仅作为面板数据属性（ClaudeOutputPane 的 runId prop），**不作为可见文本渲染**。Playwright 实测（repro_repair.py）：时间轴 item 文本为 `2026-09-02 16:00:00 agent claude-sonnet-4-5-20250514 done 耗时 30分 修复冲突完成，测试通过 查看运行记录`，body innerText 与 page source 均无 run_id。
- **佐证**：同场景其余 7 条断言全部 pass——timeline 可见、2 节点、状态转移、done、摘要、折叠面板可见、no_console_error。repair run 节点显示完整，功能符合「时间轴显示 repair run 节点（run_id 前缀 repair-），可展开查看运行记录」的意图。

### 2. repair-run-agent-label-fallback（test-defect）

- **断言**：`text_contains [.ant-timeline-item]` 包含文本 `repair-repair-agent-spec-1756905600`（repair run_id）——失败。
- **根因**：与上同源——raw run_id 不作可见文本。Playwright 实测：时间轴 item 文本为 `2026-09-02 16:00:00 repair done 耗时 30分 原地修复冲突完成 查看运行记录`，无 run_id。
- **佐证**：本场景核心意图「RUN_ID_PREFIX_LABEL 无 repair 映射 → fallback 为 agent_type 本身 'repair'」由 `text_contains 'repair'` **pass 直接验证**；'done' / '原地修复冲突完成' / timeline 可见 / 1 节点 / no_console_error 全部 pass。repair agent 标签 fallback 功能正确。

### 3. blocked-error-expand-in-list（test-defect）

- **断言**：① `element_visible [.ant-table-expanded-row]` 展开行可见——失败；② `element_visible [.ant-table-expanded-row button:has-text('清除')]` 清除按钮可见——失败。
- **根因**（双因素，均为测试设计缺陷）：
  1. **断言时序/交互契约**：列表页 error 行在数据到达时**默认全部展开**（list.tsx:544-548「受控展开：数据到达时默认全部展开（树形子级 + error 信息行可见）」）。Playwright 实测（repro_expand.py）：点击前 `.ant-table-expanded-row` visible=True 且内容完整（信息标签 + error 文本 + 清除按钮）；场景随后点击 `.ant-table-row-expand-icon` **把已展开的行收起**（display:none），再断言展开行可见 → 必然失败。场景应「先断言后点击」或点击前判定初始展开态。
  2. **选择器失效**：antd Button 对双汉字文本自动插入空格，按钮实际文本为「清 除」（清 除 之间有空格），`:has-text('清除')` 子串不匹配。实测点击前按钮已渲染但 `button:has-text('清除')` count=0。
- **佐证**：`text_contains 'Circuit breaker tripped'` pass——error 文本在页面可见；`no_click_interception` pass——展开图标可点击；`no_console_error` pass。产品在展开态正确渲染 error 信息行与清除按钮。

## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| blocked-status-label-in-list | pass | 0/6 | - |
| repair-run-in-detail-timeline | failed | 1/8 | test-defect |
| overview-problems-blocked-count | pass | 0/5 | - |
| status-filter-blocked-only | pass | 0/7 | - |
| repair-run-agent-label-fallback | failed | 1/7 | test-defect |
| blocked-error-expand-in-list | failed | 2/5 | test-defect |
| blocked-detail-page-status-tag | pass | 0/5 | - |
| blocked-detail-timeline-merge-failure | pass | 0/7 | - |
| blocked-clear-error-button | pass | 0/6 | - |

## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| repair-run-in-detail-timeline | text_contains [.ant-timeline-item] 包含文本 'repair-repair-spec-1756905600' | test-defect | 测试用例自身缺陷（非产品缺陷） | 产品时间轴渲染 agent 标签+状态+摘要+运行记录面板，raw run_id 不作可见文本（Playwright 实测 body/page 均无 run_id）；场景其余 7 条断言全 pass |
| repair-run-agent-label-fallback | text_contains [.ant-timeline-item] 包含文本 'repair-repair-agent-spec-1756905600' | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上源；场景核心意图（fallback agent 标签 'repair'）由 'repair' 断言 pass 直接验证 |
| blocked-error-expand-in-list | element_visible [.ant-table-expanded-row] 展开行可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 列表页 error 行默认自动展开，场景点击展开图标实为收起（display:none），断言时序与产品交互契约不符（list.tsx:544-548） |
| blocked-error-expand-in-list | element_visible [.ant-table-expanded-row button:has-text('清除')] 清除按钮可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd Button 渲染「清 除」（双汉字自动插空格），:has-text('清除') 子串不匹配；且行已被点击收起 |

## 建议（修复验证场景，非产品代码）

1. repair 时间轴两场景：将 run_id 文本断言改为断言 agent 标签（`text_contains 'repair'`）或断言「查看运行记录」面板可见；如需校验 run_id，改断言 `.ant-collapse` 存在或 ClaudeOutputPane 的 runId 数据属性。
2. blocked-error-expand-in-list：移除点击 `.ant-table-row-expand-icon` 步骤（或点击前断言展开行已可见）；清除按钮选择器改为 `button:has-text('清 除')` 或基于 title/role 定位。

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

