# 提案：审查车道纯文本轮输出纪律收敛

## 背景

纯文本轮离群维（无工具调用的模型回复轮，轮数>100 且占比>50%）在 code-review 车道连续两窗命中（code-review-1795190463 为 50.47%、code-review-1795277035 为 58.23%，单 run 2102 个纯文本轮），code-fix 车道本窗两个 run 首窗命中（56.45% 与 51.28%）。检测机制（2026-11-04-evo-refine-midflight-outlier-dims 交付）与响应机制（evo-text-turn-inflation-response 交付）均已生效，但响应机制的输出纪律按其 proposal 明文只覆盖 planner-plan 车道（「其余车道模板不动」），未覆盖车道机制生效后已连续 6 窗持续命中（序列 2/0/0/0/1/3）无收敛。

## 目标

把 evo-text-turn-inflation-response 已在 planner-plan 车道验证的输出纪律形态（结论与发现先行、压缩逐轮叙述性输出）扩展到 code-review 与 code-fix 两个车道模板，压降纯文本轮占比；同时登记对照基线与止损观察口径，为后续模型版本对照处置留好判据。

## 非目标

- 不改动 planner-plan 车道既有输出纪律（已生效，本窗该车道零命中）。
- 不改动检测机制与阈值（midflight-outlier-screening 原样）。
- 不做模型版本切换或对照试验本身（仅登记止损判据，观察期内占比无压降才转架构处置）。
- 不引入任何输出长度数字上限（agent-prompt-authoring 知识页规则）。