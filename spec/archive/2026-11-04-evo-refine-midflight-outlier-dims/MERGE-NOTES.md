# 范围收窄（2026-10-30 人工全量核查）

- 部分成立裁定：turns 维误报源已被在飞 evo-add-run-metrics-lane-baseline 消除（tasks 全勾；1.1 分组键兜底＋2.1 批量车道 turns P90 已落 self_review.py:1001-1133）。其 tasks 全勾且不含本范围——不合入不重开，本 SPEC 收窄为独立小案。
- 剩余三件：①self_review.py:824 MIDFLIGHT_OUTLIER_DIMS 中 cost_usd/duration_seconds 恒组中位×3（:1107），函数内无按条目归一除法；②text_turns 维度缺位（全文件零命中）——纯文本轮通胀恰是批量 run 误报主形态；③model 字段缺位（不同模型轮数不可比）。
- 损失面：误报仅进自省摘要无自动动作（:810 降噪铁律在），代价=每窗一轮演化复核注意力＋摘要噪音。
