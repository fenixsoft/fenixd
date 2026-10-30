# 提案：对齐 code-fix 修复链的 skip_reason 枚举契约并加链级零进度护栏

## 背景与问题（已核实）

- code-fix 修复链对台账条目的「误报/不值得修」豁免硬出口要求 fixer 产物行的 skip_reason 命中白名单。runner 读侧 core/code_fix.py:125 定义 IGNORE_ELIGIBLE_SKIP_REASONS（false_positive、not_worth_fixing 两个枚举），:2808-2816 _split_fix_rows 对 skip_reason 做集合成员整串精确匹配；带任何后缀即脱靶，脱靶 skipped 行直接不收录、无任何日志。
- fixer 模板 agents/code-fix.md 一边要求裸枚举（:84-88），一边自带后缀先例（:97 末尾附 (no_marker)）与「在 skip_reason 或回复中说明」（:24），且产物 schema（:76-81）没有独立解释字段——模型自然把解释文本并进 skip_reason，精确匹配必脱靶。
- 已发生损失（dsh-plugins 项目）：台账条目 5ae61ac429c4（源码已有 fenix-ignore 豁免标记，fenix-skill-provider/src/host/frontmatter.ts:181）全链空转 13 个 run、约 27 分钟、$6.18：前窗 2 个 run + 本窗 10 个零产出 run（fenixd.log 10-16 18:18:36Z 至 22:48:28Z 共 9 条 chain_exhausted rollup，resolved=0、ignored=0）+ 第 11 班收尾 run 恰写裸枚举才 chain_converged。夜静窗守卫（core/code_fix.py:3249，缺省 04:15-04:45）还替本链拦下 20:15Z 一班。

## 提案（三件事）

1. 读侧前缀归一：skip_reason 去首尾空白后以白名单枚举值开头即命中豁免硬出口，完整原文并入 mark_ignored 的 reasons（core/code_review.py:2157 已有该形参，零接口改动）；脱靶 skipped 行记 warning 日志不再静默。
2. 模板契约对齐：agents/code-fix.md 收紧为 skip_reason 只允许裸枚举，解释文本挪独立可选字段 reason；(no_marker) 规则与 :24 表述同步修正，产物 schema 增补 reason。
3. 链级护栏：同链连续 2 轮 resolved+ignored=0 即发 admin 信号并暂停该链自动重派（现状无任何此类护栏，链收敛靠模型偶然写对裸值，少烧一班靠夜静窗偶然）。

## 与存量工作的关系

- 在途 evo-add-codefix-anomaly-redispatch-budget（回归异常形态重派预算）与 evo-codefix-zero-face-regression-hardening（回归异常检测口径）同属「零产出防烧」家族，但对象均为回归失败批，不覆盖本提案的枚举口径与链收敛护栏；其余 5 个 codefix 相关在途 SPEC 亦不覆盖。
- 归档 2026-10-13-evo-codefix-night-quiet-window 是本链依赖的夜静窗守卫本体，与本提案互补而非重复。

## 非目标

- 清理 dsh-plugins 仓 6 个已合并未删的 fenix/code-review-fix-* 分支属运维杂务（todo 已留痕），不入本 SPEC 交付物（注意 fenixd 主仓同模式分支有 283 个，勿混淆仓库）。