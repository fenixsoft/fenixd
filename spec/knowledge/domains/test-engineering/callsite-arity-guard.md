<!-- knowledge: capability=callsite-arity-guard rev=1 sources=spec/archive/2026-09-20-add-control-plane-silent-failure-guards -->

# 生产调用点实参数量守卫

静态 AST 守卫测试，拦截生产代码调用点上「实参数量不足以满足方法必填位参」的静默缺陷。

## 现行规则

- 扫描范围为生产代码调用点：`core/**/*.py` 与仓库根 `fenixd.py`；对每个 `<obj>.<method>(...)` 调用判定——调用提供的位置参数个数少于该方法定义的最小必填位置参数个数，且调用不含 `*args` 展开（`ast.Starred`）与 `**kwargs` 展开（`keyword.arg is None`）时判违规，报出 `文件:行 类.方法 调用给 N 个 / 要求 M 个`。
- 判定仅在方法名于 `core/` 中唯一签名、且该签名不含 `vararg`/`kwarg` 时生效；同名多签名（≥2 个不同签名）的方法名整体不参与判定，避免跨类同名误报。
- `self.<method>(...)` 同类内调用一并覆盖；`staticmethod` 首参不剥离，实例方法/类方法剥离首个 `self`/`cls` 后再比对。
- 关键字补足不误报：调用的关键字名属于该方法签名时，视为满足对应必填位参。
- 误报白名单条目粒度为 `(文件相对路径, 行号, 方法名)` 或等价最小粒度，禁止文件级或全局通配豁免整类。
- 守卫自带「有牙」自检：断言候选方法集规模非空且高于下限，规则退化导致候选集归零时自检失败，守卫不得永久绿。

## 溯源

- [2026-09-20 add-control-plane-silent-failure-guards](spec/archive/2026-09-20-add-control-plane-silent-failure-guards/) — 新增静态 arity 守卫：唯一签名保守判定、变长/关键字补足不误报、最小粒度白名单与候选集自检；落地实证白名单外违规数为 0
