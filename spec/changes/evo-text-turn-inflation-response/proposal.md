# Proposal: text-turn-inflation-response

## Why

纯文本轮（无工具调用的模型回复轮）离群维度五窗无响应端落地：planner-plan 车道四连窗命中（11-04 一 run→11-05 三 run→11-06 两 run→11-12 一 run），11-12 窗扩散到 admin/arbiter/planner-judge/planner-plan 四车道（占比 54.5%-61.9%），admin 与 arbiter 处置链车道首次命中；档案级复核超阈值 run 达 31 个/9 车道、model 均 glm-5.3-flash。历史实测曾因该噪音白跑一轮演化复核（10-17）。检测 spec evo-refine-midflight-outlier-dims 三项交付均为观测端；积压草稿 add-outlier-aggregation-outlet（4b51f67105a7）承接对照报告面，但其非目标明文「不自动修改 planner 提示词或 provider 路由」——响应端双缺口无任何承接（评审时点注记：该草稿队列已清空且未晋升 spec/changes，报告面承接载体暂不在案、留痕见 .fenix/evolution/.build/emit_4d7b35560107.py，报告面待后续另行立项，不影响本 spec 响应端两交付）：①token 面不可量化（逐消息用量累计全零：网关逐消息不回传用量 runner.py:7377-7418，真实用量仅在 run 末 last_result，即 result 事件 :7440-7441，且未回填 run_metrics）；②重灾区车道无输出纪律约束。本 spec 只做响应端剩余面，与该草稿显式互补（报告面归草稿、响应面归本 spec）。

## What Changes

- run_metrics 用量回填：终态落盘 run_metrics 时，若逐消息累计用量全零，则从 last_result 真实用量回填 input_tokens/output_tokens 等计量字段并标注来源；逐消息累计非零时不覆盖。
- planner-plan 输出纪律约束：agents/planner-plan.md 模板增加简洁性/输出纪律条款（压缩逐轮叙述性输出指引），形态仿 agents/planner-judge.md:88 既有先例；其余车道模板不动（admin/arbiter 按条目建议留痕至第二窗命中后纳入）。

## Impact

- Affected specs: agent-runtime（新能力页）
- Affected code:
  - core/agent_runner/runner.py（终态 metrics 用量回填）
  - agents/planner-plan.md（输出纪律条款）
  - tests/test_run_metrics_usage_backfill.py（新增单测）