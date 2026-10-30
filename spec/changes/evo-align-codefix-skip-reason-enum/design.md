# 设计：align-codefix-skip-reason-enum

## 改动面

1. core/code_fix.py 的 _split_fix_rows（:2999-3028，白名单判定 :3025）：白名单判定从集合成员整串相等改为「strip 后以任一枚举值开头」，先试整串相等快路径再试前缀；skip_reason 缺失或非字符串按未命中处理（现状集合成员判定对 None 天然安全，改前缀后 MUST 保持不抛异常）；命中时把 skip_reason 完整原文与产物行 reason 字段（若有）组装进传给 code_review.mark_ignored（core/code_review.py:2343，reasons 形参 :2344）的 reasons 映射——调用点 :3051-3055 已传 reasons=skip_reasons，只需改值语义（mark_ignored 把 reasons 值原样记入 ignored_reason，自由文本无接口改动）。
2. 同函数对 skipped 且脱靶的行新增 warning 日志（沿用模块既有 lenient logger 形态），不改变其被丢弃的语义。warning 范围限定「非空字符串、既不命中白名单（裸值/前缀）也不属既有 skipped 词汇表（unfixable/needs_human）」——unfixable/needs_human 是模板既有保持-open 出口（agents/code-fix.md:93-97），缺省（无 skip_reason）同为现状静默；对它们记 warning 会把正常出口变噪音、淹没真脱靶信号。
3. agents/code-fix.md：:83-90 产物 schema 增补可选 reason 字段；:93-98 枚举说明补「MUST 写裸值、解释写 reason」；:106 (no_marker) 规则改写；:24 表述同步修正。
4. 链级护栏：在各链终局写点统一维护「连续零进度轮数」——全部终局触发（chain_converged :4573/:5031、chain_exhausted :5046、chain_superseded :4852、wip_overlap_blocked :5087）都经 _chain_terminal_fields → _emit_chain_rollup（:5425-5467）出账，且出账后链级计数归零，故每次 rollup 的 resolved+ignored 天然是逐轮增量：零进度=当轮 rollup 的 resolved+ignored=0。计数与暂停标记随链级进度字段持久化（沿用既有 phase=blocked 进度落盘与文案分流体系，core/code_fix.py:4464-4465、:5061）；达到 2 时经既有告警落盘通道发 admin 信号（形态参照夜静窗守卫的 AdminStore 信号写入，:3655-3768）并暂停自动重派；解除复核挂在既有 select_batch 选批扫描与人工处置入口（manual 授权/重派），解除条件见 spec R4。

## 取舍

- 前缀归一而非读侧正则抽取解释文本：模板侧同时收紧为裸枚举+独立 reason 字段，两侧在过渡形态（带后缀）上仍互认，兼容存量产物与模型回退行为。
- 护栏阈值取 2 轮：与 30 分钟投递闸（dsh-plugins .fenix/config.yaml poll_interval_minutes: 30）相乘，最坏约 1 小时熔断，对比本次 13 个 run/约 6 小时空转。
- 不改 IGNORE_ELIGIBLE_SKIP_REASONS 集合本身，保持「缺省保守：必须显式声明」语义（core/code_fix.py:121-125 注释）。

## 风险

- 前缀匹配理论上可能误命中未来新增的枚举变体——当前枚举集合封闭（两值）且模板已禁止后缀携带新语义，风险可忽略。
- 护栏暂停后若豁免标记被人工移除、条目确需修复，依赖 R4 解除条件（人工处置或新一轮评审产出台账变更）兜底。
