# ADR-076：LLM 裁决 run 化派发，daemon 机械执行裁决

date: 2026-09-12
status: accepted

## Context

交付物声明「声明 vs 现实」的语义矛盾（多 basename 命中、语境等价）原理上需要 LLM 裁决，但两条路都走不通：agent 手改 SPEC 文档不可审计、不可回滚；daemon 内直调 LLM API 需新开鉴权/记账/路由通道，违背「一切 LLM 交互走 agent run 车道」的既有架构（ADR-055）。

## Decision

- 一切 LLM 裁决以轻量单轮 agent run 派发（`dispute-judge-` 等前缀注册进 `_RUN_PREFIXES`），复用既有 agent run 车道的模型路由、成本记账与超时控制；daemon 内不直调 LLM API。
- judge 只读不写：主树 `--add-dir` 只读上下文、无 worktree、无写权限任务书，只输出裁决 JSON（`.fenix-run-result.json` 顶层 `status: "success"` + `verdicts` 数组），不执行、不改任何文件。
- daemon 按 verdict 机械执行确定性文本操作（声明条目 path/kind 替换）并重跑守卫——裁决 → diff → 审计全程 daemon 可控，人工可回滚。
- 防洗白闸门：修正声明 ≠ 放行缺件。typo 修正后重跑守卫，文件必须在实现分支真实存在才推进；actual_path 也缺失时按缺件走既有打回路径，judge 无权放行不存在的文件。
- judge 失败/超时/JSON 不合法等价 `unclear`，转既有人工通道，不自动重派；裁决全文 + diff + run id 落 dispute 审计 jsonl（含 confidence），人工可发现系统性谎报。
- judge 提示词把实现者 findings 明确标注为「主张」，要求以仓库实际文件与 spec 语境独立核实（防实现 run 提示词注入洗白）。

## Consequences

- 正常路径零开销：仅缺件场景触发 judge，分钟级延迟对比烧一整轮重派是净省。
- LLM 裁决的质量风险由「机械执行 + 守卫重跑 + 审计可回滚」三重兜底；后续新增 LLM 裁决场景照此形态接入，不允许 LLM 直接持有写权限。
