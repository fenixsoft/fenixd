# 设计：场景断言 schema 单源化与写前预校验

## Context

2026-09-13 两批次 100% 剔除（fenixd.log 6884/6958）：planner 生成 25 条 scale-estimate-*（output_match 缺 expected）与 17 条 blind-run-marker-*（json_output 缺 step）全部被写端校验拒绝，触发退回 plan+重跑 planner（1789282524）。校验规则在 core/verify_engine/scenarios.py:585-600，planner 指令在 agents/planner-plan.md:94-96 仅列类型名——两处分裂，LLM 只能猜结构。17650012 修了读侧迁移，写侧未动。

## Goals / Non-Goals

- **Goals**：生成侧产出的断言结构满足写端校验；非法条目写前逐条剔除，避免整批重跑。
- **Non-Goals**：不改校验规则本身（拒绝语义保留）；不做场景运行时执行器的改动；不引入外部 schema 文件（单源锚定在 scenarios.py）。

## Decisions

### D1：单源锚定在 core/verify_engine/scenarios.py 派生

**选择**：把必填字段规则收敛为 scenarios.py 中可被引用的权威结构（如 REQUIRED_FIELDS 常量或从现有校验分支抽函数），planner prompt 的渲染侧读取该结构生成字段说明。

**理由**：该校验器已是词表权威源（planner-plan.md 自注『以代码为准』），扩展为字段级权威源零范式切换；校验与生成自然同源。

### D2：prompt 注入与写前客户端预校验双保险

**选择**：planner-plan.md 内联必填字段与样例（降低生成侧错误率）+ 写盘前客户端预校验逐条剔除（兜底拦截，防单条毒化整批）。

**理由**：前者治本（LLM 少犯错），后者治标（错误不扩散）；两者成本都低，共用同一单源规则。

### D3：预校验复用写端校验函数

**选择**：写盘前调用与写端相同的 validate_scenario（scenarios.py），逐条报告。

**理由**：保证预检与终检同口径，杜绝『预检过了终检失败』的二次分裂。