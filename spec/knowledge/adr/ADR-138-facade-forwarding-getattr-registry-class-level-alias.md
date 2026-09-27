# ADR-138：门面转发以 __getattr__ 显式注册表统一委托，静态式转类级别名

date: 2026-09-22
status: accepted

## Context

巨型类拆包后宿主类沉淀数百个一行转发方法（多个门面合计 260+），形成双份签名/docstring 维护与三层调用链；而转发方法调用点近两千处、其中绝大多数是测试，删除转发改调用方直连会大面积破坏调用点与 `patch.object` 缝隙，与「零行为变化」红线冲突。

## Decision

- 宿主类以 `__getattr__` + 源码内联显式注册表统一委托：未命中名严格 `raise AttributeError`（hasattr/getattr 默认值语义不得恒真），dunder 名一律不转发；注册表 MUST 内联声明、禁动态反射扫描子模块生成。mock 写实例 `__dict__` 天然遮蔽 `__getattr__`，`patch.object(facade, X)` 进出语义保持兼容。
- 首参非 `self`/`pipe` 的静态式转发 MUST NOT 纳入实例注册表：类直调（`Cls.<名>`）不经实例 `__getattr__`，`partial(func, self)` 对无 self 首参的函数会多注一个 self 直接 TypeError；此类名字以类级别名（`staticmethod(...)` 纯对象绑定，不书写签名与 docstring）收敛，保留 `Cls.<名>` 与 `self.<名>` 两条解析路径；链式别名目标必须是收敛后仍存在的类属性。
- 类上既有的 `__getattr__`（如部分构造懒推导）增量扩展、MUST NOT 重写覆盖，原分支优先级保持。
- 契约测试为覆盖性硬门：枚举原转发方法全集逐一断言可解析且解析到与子模块实现同一函数对象（不以 `__name__` 为断言口径），并逐名断言未知名/dunder/类直调点行为。

## Consequences

- 宿主类真正变小（删转发方法体），双份签名消失，零调用点破坏；注册表本身成为比数百个一行方法更集中的单一事实源。
- 注册表遗漏一个名字即运行时 AttributeError，覆盖性测试是硬门；IDE 补全退化可补 `__dir__` 缓解。
