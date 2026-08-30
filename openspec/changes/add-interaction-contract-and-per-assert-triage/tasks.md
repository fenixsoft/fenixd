# Tasks: add-interaction-contract-and-per-assert-triage

实现依据（实施 agent 必读）：
- 能力定义 `specs/interaction-contract/spec.md`；设计决策 design.md D1-D5
- 上游依赖：add-verdict-evidence-taxonomy（四分类机制、verdict_check.py、assertion evidence）已合流
- 场景生成：`.fenix/core/agent_runner.py` planner prompt + `.fenix/core/verify_scenarios.py`（scenarios.json）
- 裁决校验：`.fenix/core/verdict_check.py`；报告合成：`.fenix/core/verify_report.py`
- 真实夹具：v2-overview-page 事故（卡片跳转缺失 + 6 场景整体豁免，commit 84de42e 为人工热修）

## 1. 交互契约（场景生成侧）

- [ ] 1.1 契约校验器：可交互候选识别（首版模式：button-group/button/cards 循环/href 与 link 字样 className）+ 场景覆盖 diff + 纯展示声明登记
- [ ] 1.2 planner prompt 注入契约要求（交互场景必覆盖或声明纯展示）；scenarios.json 元数据记录 covers/declared-display
- [ ] 1.3 覆盖不完整 → 输出校验失败并要求 planner 补齐（复用裁决重试路径）

## 2. 裁决逐断言归因

- [ ] 2.1 裁决 prompt 输出扩展：failed 场景每条失败断言单独 assertion_triage（四分类 + evidence）
- [ ] 2.2 verdict_check.py 扩展：failed 场景缺 assertion_triage 或含 product-bug 断言时禁止场景级豁免
- [ ] 2.3 verify_report.py 渲染「断言级豁免清单」小节（旧报告无字段时缺省）

## 3. 实现任务书契约条款

- [ ] 3.1 implementer prompt 加固定条款：可交互元素需 SPEC 定义或任务书声明；「待裁决交互」写入 run-result findings

## 4. 单元测试

- [ ] 4.1 覆盖：候选识别（v2-overview-page 卡片形态）；覆盖缺失被拦；纯展示声明放行；单断言 product-bug 阻止场景豁免；全断言非产品缺陷可豁免；豁免清单渲染
- [ ] 4.2 用 v2-overview-page 真实报告（12 场景 6 豁免）作夹具回归：豁免清单应逐条列出被豁免断言

## 5. 验证与打包

- [ ] 5.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [ ] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包
