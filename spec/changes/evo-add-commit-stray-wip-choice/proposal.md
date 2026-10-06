## Why

主树散件 WIP 滞留信号（maintree_stray_wip_stale）10-02 以来四度出现、四次各烧一个 admin 会话做同一裁决（核对归属→提交），裁决选项注册表 9 桶 15 选项中无任何提交类动作，四次处置全部 choice_id=None（自由处置）。commit_stray_wip 已被处置会话在 10-03（记录 4c8be9a8ea40）与 10-06（记录 4a1464085660）两次按契约回填 suggested_choice 建议、零次被消费——建议-消费回路断裂实锤。登记一次即可把复发裁决代价塌缩。

## What Changes

1. 注册表登记：_ADJUDICATION_REGISTRY 新增 maintree_stray_wip_stale 桶与 commit_stray_wip 选项（spec_scoped=False，语义按两次 suggested_choice 原文：核对归属后直接提交散件 WIP、与 stash 类动作互斥、处置记录附提交 hash）。
2. 执行器：execute_adjudication_choice 新增分支与执行函数——只提交信号清单内文件，结果附提交 hash。
3. 信号带出：发射点记录补 choices 快照（照 mergeback 先例），recommended_action 文案带出选项 id，SIGNAL_RECOMMENDATION 同文同步。

## Out of Scope

- 不做 stash/discard 姊妹选项（可后续按同型追加）。
- 不改 STORED_SIGNAL_TYPES 摄取唤起策略（自动唤起的 admin 会话仍会做归属核对，「代价近零」指 Dashboard 人工点击路径；是否让已带 choices 的信号降级为等人工点击另行评估）。
- 不动前端（choices 通用渲染，缺键回退注册表）。