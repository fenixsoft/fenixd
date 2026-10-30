# 设计：align-codefix-skip-reason-enum

## 改动面

1. core/code_fix.py 的 _split_fix_rows（约 :2808-2816）：白名单判定从集合成员整串相等改为「strip 后以任一枚举值开头」，先试整串相等快路径再试前缀；命中时把 skip_reason 完整原文与产物行 reason 字段（若有）组装进传给 code_review.mark_ignored（core/code_review.py:2157）的 reasons 映射——调用点约 :2842 已传 reasons=skip_reasons，只需改值语义。
2. 同函数对 skipped 且未命中白名单的行新增 warning 日志（沿用模块既有 lenient logger 形态），不改变其被丢弃的语义。
3. agents/code-fix.md：:76-81 产物 schema 增补可选 reason 字段；:84-88 枚举说明补「MUST 写裸值、解释写 reason」；:97 (no_marker) 规则改写；:24 表述同步修正。
4. 链级护栏：在链收尾既有判定点（chain_converged 约 :4241/:4693、chain_exhausted 约 :4708、_emit_chain_rollup 约 :5062-5080）维护「连续零进度轮数」：零进度=resolved+ignored=0。计数与暂停标记随链状态持久化（沿用链 blocked 状态的既有落盘位置）；达到 2 时经既有告警落盘通道发 admin 信号（形态参照夜静窗守卫的入窗/出窗告警）并暂停自动重派；解除条件见 spec R4。

## 取舍

- 前缀归一而非读侧正则抽取解释文本：模板侧同时收紧为裸枚举+独立 reason 字段，两侧在过渡形态（带后缀）上仍互认，兼容存量产物与模型回退行为。
- 护栏阈值取 2 轮：与 30 分钟投递闸（dsh-plugins .fenix/config.yaml poll_interval_minutes: 30）相乘，最坏约 1 小时熔断，对比本次 13 个 run/约 6 小时空转。
- 不改 IGNORE_ELIGIBLE_SKIP_REASONS 集合本身，保持「缺省保守：必须显式声明」语义（core/code_fix.py:118-124 注释）。

## 风险

- 前缀匹配理论上可能误命中未来新增的枚举变体——当前枚举集合封闭（两值）且模板已禁止后缀携带新语义，风险可忽略。
- 护栏暂停后若豁免标记被人工移除、条目确需修复，依赖 R4 解除条件（人工处置或新一轮评审产出台账变更）兜底。