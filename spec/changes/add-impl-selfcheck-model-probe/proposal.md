# add-impl-selfcheck-model-probe 提案

## Why

全历史实现失败重做 207h（8.6%），实证三类重烧源：①**结果文件契约类失败引发整轮重烧**——dispositions 字符串数组格式陷阱令 add-impl-ocr-parallel-lane 连烧 r2/r3 两轮（agent 看不到 daemon 侧门禁报错、下一轮照抄上一轮坏形状）；②**provider 拒模型秒死循环**——maomaoai/deepseek-v4.1-flash unrecognized_model→Exit 1 零 token，近 48h 内 22 个 impl run 秒死（fix-relocation-writeback-layer 一晚 12 个、每 2-5 分钟一个同因重派）；③**回归双跑**——implementer run 内手工跑全量回归（单次 8-10m，实测最长 10m 占 run 关键路径），而框架侧回归模块（core/regression.py，add-test-regression-tab 已落地）在 testing 阶段必然再跑一遍，纯重复。本 SPEC 目标：把三类重烧源在前端消灭。

## What Changes

- **收工自证命令（门禁自检前移）**：将 `core/agent_runner/result_gate.py` 的生产校验体暴露为零网络 CLI 自检入口（如 `python3 -m core.agent_runner.result_gate --selfcheck <结果文件>`，退出码 0/1 + 违规明细 stderr）；implementer 收尾检查 prompt 注入「结果文件写完必跑自检、非零退出不得收工」；任务书模板补 dispositions 必须为对象数组的正反例。agent 在退出前即可发现并修复形状错误，不再依赖 daemon 侧打回重派。
- **模型链拒模型快速 failover**：`unrecognized_model`（provider 明确返回的无效模型错误类别）不再走 transient_retry 同因重派循环，改为立即沿 provider 链 failover 到下一可用模型并记 WARNING 告警（供摘除决策）；`config.template.yaml` 默认模型链摘除实测 12 次拒模型的 `maomaoai/deepseek-v4.1-flash` 条目（运行时 `.fenix/config.yaml` 的同步修改为人工运维步骤，写入文档，不进任务门禁）。
- **回归双跑合并**：implementer 收尾不再要求 run 内跑全量回归——`quality-gates.json` 的 `full-suite` 门数据源切换为「框架侧回归车道产物优先，run 内自查降级为可选兼容来源，均无则 pending（fail-open）」，读侧合成顺序固化；收尾自查 3 项中的全量回归改为「仅当框架侧回归产物不可用时才在 run 内执行」的降级路径。全量回归的判定责任单点化到验证链。

## Capabilities

### New Capabilities

- `impl-result-selfcheck`: 结果文件收工自证 CLI 的形态、退出码语义、prompt 注入契约、正反例模板要求。
- `model-chain-health-probe`: unrecognized_model 的错误分类识别、链上 failover 行为、告警与模板默认链修订。
- `impl-regression-delegation`: 回归责任外包后的 quality-gates `full-suite` 门数据源优先级、implementer 收尾自查项调整、兼容条款。

### Modified Capabilities

- `quality-gates-progress`: `full-suite` 门的判定数据源从「run 内自查必跑」扩展为「框架侧回归产物优先 + run 内自查降级兼容」，状态语义（passed/failed/running/skipped/pending/unknown）不变；读侧合成顺序在本 delta 中固化。

## Impact

- **agent_runner**：`core/agent_runner/result_gate.py`（自检 CLI 入口，校验体复用不改判定）、`core/agent_runner/prompt_builder.py`（收尾检查注入段：自检要求 + full-suite 降级路径）、`core/agent_runner/provider_circuit.py` 或模型链选择处（unrecognized_model 分类与 failover）。
- **提示词模板**：`agents/implementer.md`（收尾契约段；该文件主树当前存在未提交 WIP，merge-back 冲突风险在设计 Risks 中评估）。
- **配置模板**：`.fenix/config.template.yaml`（默认模型链摘除无效模型条目；入库文件可交付）。
- **Dashboard 读侧**：`core/dashboard/data/` 门禁合成处（full-suite 数据源优先级），无前端改动。
- **框架回归联动**：`core/regression.py` 产物路径与读侧对接（不修改回归判定本身）。
- **测试**：result_gate 自检 CLI 用例、failover 分类用例、门禁合成优先级用例。
- **风险面**：自检入口被 agent 忽略（prompt 强注入 + daemon 侧既有门禁保持不动作为兜底，双保险）；failover 错误分类误判（仅严格匹配 unrecognized_model 类别，其余错误路径行为不变）；回归外包后 impl 失去快速回归反馈（frontend-build 与交互契约自查仍在，回归缺陷走既有 bug-found 环）。
