# Proposal: add-cost-observability

## Why

单 spec 的 token 消耗不可观测：v2-config-page 24 小时烧掉 4,200 万+ input tokens（runs/*.jsonl 可考古部分），但 STATE.md、验证报告、Dashboard 全都不展示；网关不回传成本字段导致金额恒为 $0.00。用户只能事后手工解析 jsonl 考古（复盘改进点 6）。没有观测就没有预警，烧钱失控只能在事后发现。

## What Changes

- run 收工时从 stream-json 结果提取 usage（input/output/cache tokens），累计持久化到 STATE.md 内部字段 `_tokens_in` / `_tokens_out`（per-spec 生命周期累计）
- 验证报告与 Dashboard SPEC 详情展示累计 token（与 _verify_fail_rounds 等治理字段同区）
- 新增预算告警：配置 `agents.token_budget_millions`（单 spec 累计 input 百万 token 上限，缺省 50；0=关闭）——达到 80% / 100% 均发警告级告警（2026-09-01 用户降噪决策，100% 不再发严重事件；spec 继续跑不自动冻结，由人工决定是否处置）
- 金额展示：网关回传成本时展示金额，不回传时仅展示 token 数（不伪造金额）

## Capabilities

### New Capabilities
- `cost-observability`: per-spec token 消耗统计、展示与预算告警

### Modified Capabilities

（无）
