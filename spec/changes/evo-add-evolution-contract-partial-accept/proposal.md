## Why

自进化产物校验对单条目契约错误（小节名越界三值枚举等）是整份 raise ContractError 拒绝：合法条目陪葬、约 19 美元的 396 turns 白烧、下检查点全量重跑。输入侧读 todo.md 对未知小节是「跳过+WARNING」的宽口径（core/evolution.py:550-558），既有部分恢复语义也只覆盖「条目不足」（core/agent_runner/maintenance_runs.py:1088-1105 的 partial 分支）与流式截断 .parts（evo-add-evolution-product-salvage），单条非法恰无任何中间路径，失败现场产物文件还被清理删除。本次实际损失已由自动重试全额自愈（$27.36 重跑浪费、无材料缺席），但全量重跑浪费在每次枚举幻觉时必然复现。

## What Changes

1. 校验宽口径：read_contract 对单条目契约错误改为收集错误并跳过该条、合法条目照常返回；全部条目非法仍整体拒绝。
2. 落库对齐：maintenance_runs 的 ContractError 分支接入既有 partial 语义（落合法条目、run_ok=False、水位不推进，下检查点幂等补齐），失败现场产物文件留档不删。

## Out of Scope

- 不做「带错误回问修复」回路：现有检查点自动重试已实测可自愈，回问需新起小型修复调用、实现重边际价值低。
- 不改提示词：agents/evolution.md:48 产物 schema 已显式给出三值枚举（2026-09-13 起），补示例无增量价值。
- 不放非法条目入库：校验拒绝本身正确，本 SPEC 只改「拒绝的粒度」。