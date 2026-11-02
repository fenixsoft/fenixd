# 合并增量（2026-10-30 人工全量核查）

折叠条目：7d6b9edcbd23、42359d671abf。本草稿已是三源合流形态；42359 方向补齐说明：

- 双向否决一次补齐：daemon error 否决 succeeded（maintenance_runs.py:2131-2135 硬门拦截翻 run_ok=False→terminal=error，而 self_review.py:499-526 `_classify_run` 只读产物尾行从不查 daemon terminal——succeeded→failed 方向当前代码不存在）＋ daemon success 否决 marker/error 终态误判（7d6b③/d81a①）＋ marker 声明形态锚定（7d6b①：`_business_fail_marker` 头部 100 字符子串命中即 failed，self_review.py:360-373/:172/:503-505）。
- 设计变更须显式推翻三个先例：10-03「marker 有意不拦」spec 决策、tests/test_self_review_terminal_crosscheck.py:249 pinned 语义、self_review.py:601-603 docstring「MUST NOT 纳入守卫」。防误伤边界（查无账面行保守保持 failed）按本草稿既有条款。
- **串行约束**：与在飞 evo-fix-self-review-phantom-running（tasks 10/10 全勾、已实现待归档，明文冻结 result/error 分支语义）串行流转——本 SPEC 实施须待其归档后开工。
- 附带（d81a 自有）：salvage 路径 turns=0 无档案侧回填致 turns/cost 双账分裂（maintenance_runs.py:1460/:1491-1517）。
