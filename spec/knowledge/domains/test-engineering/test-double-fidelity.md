<!-- knowledge: capability=test-double-fidelity rev=1 sources=spec/archive/2026-09-20-add-control-plane-silent-failure-guards -->

# 测试替身签名保真守卫

静态 AST 守卫测试，约束 `tests/` 内测试替身（fake/stub）方法的签名不得比生产方法更宽容，杜绝替身静默吸收参数。

## 现行规则

- 守卫扫描 `tests/**/*.py` 中所有类定义的方法，对方法名与生产方法匹配者比对三元组 `(必填位置参数个数, 是否含 *args, 是否含 **kwargs)`。
- 违规判定：替身比生产方法更宽容（含 `*args` 或 `**kwargs`）判违规；替身必填位置参数少于生产方法判违规；替身必填更多不判违规（会在测试执行时当场 `TypeError`，无静默风险），报出 `文件:行 类.方法 fake=(req,vararg,kwarg) prod=(req,vararg,kwarg)`。
- `self`/`cls` 剥离规则与 callsite-arity-guard 一致；`staticmethod` 不剥离首参。
- 候选 seam 构造：参与比对的生产方法名须在 `core/` 中唯一签名、签名不含 `*args`/`**kwargs`、非 dunder、且不在宽泛名黑名单内（logger 风格 `info`/`warning`/`error`/`debug`/`critical`/`exception`/`log`/`_log`；容器风格 `get`/`items`/`keys`/`values`/`append`/`update`/`read`/`write` 等；时间工具 `now`/`isoformat` 等）。
- 白名单豁免确有意为之的宽容替身，粒度为最小 `(文件, 类名, 方法名)`。
- 测试替身一律写成与生产方法一致的显式签名，不以 `**kwargs` 吸收参数；守卫运行违规数为 0（白名单为空即可通过）。
- 守卫自带「有牙」自检：断言候选 seam 方法集规模高于下限，退化即失败。

## 溯源

- [2026-09-20 add-control-plane-silent-failure-guards](spec/archive/2026-09-20-add-control-plane-silent-failure-guards/) — 新增替身签名保真守卫（宽容替身/欠必填报违规、seam 候选黑名单、有牙自检），并同步收紧 4 个测试文件内的既有偏离替身为显式签名，守卫零欠债落地
