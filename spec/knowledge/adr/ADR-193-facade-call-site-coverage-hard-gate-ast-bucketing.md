# ADR-193：门面字面调用点覆盖性硬门——AST 扫描、目录分桶、悬空反向断言

date: 2026-09-29
status: accepted

## Context

门面转发以 `__getattr__` + 源码内联显式注册表统一委托（ADR-138），未注册名在运行时抛 AttributeError。生产已两次命中同型事故：调用点写 `self._pm.<名>` 而真身在 mixin 上、注册表漏登记（`_disputed_deliverables`、`_preclassify_drift`），异常被派发函数级 try 兜住后整轮回滚、retryable 退避重派，白烧 run 预算。既有覆盖测试只断言注册表单名存在性，对「调用点 → 门面可解析」方向零覆盖；漏注册只能靠生产 AttributeError 事后取证。

## Decision

- 「门面字面调用点必须可解析」是测试硬门：AST 扫描 core/**.py 全部 `self._pm.<名>` 字面属性链，逐一断言可经所属门面解析。运行时 `dir()` 枚举被否决——惰性 property 会在枚举时触发构造，误伤面大；AST 对静态字面量全量可见且无导入副作用。
- 解析域 = 注册表键 ∪ 门面显式定义：`dir(cls)` 覆盖 MRO 混入方法、类属性、staticmethod 别名与惰性 property（dir 只列名不访问，不触发惰性构造）；方法体内 `self.<名> = ...` 实例属性赋值按 MRO 各类源码 AST 推导（漏了实例属性必自伤）。dunder 除外。豁免机制必须显式：静态式转发名与 fail-soft 探测点入显式名单并附注释理由，失败信息按「注册表/显式/豁免」三归属可辨，评审时可辨真缺口。
- 扫描域按目录分桶归各自门面：`core/pm_engine/**` 的 `self._pm` 回引对 PMEngine 解析，`core/agent_runner/**` 的对 AgentRunner 解析——组件文件的 `self._pm` 回引的是哪个门面取决于宿主，混扫必误报；未入桶调用点即失败，分桶必须完备。VerificationPipeline 侧禁止 `self._pm` 私有回引，仅做注册表反向断言。
- 反向断言查悬空而非查死键：每条目目标须可在其门面上解析（按条目形态适配——二元组经惰性 property + getattr 链、模块函数单值直解析）；「键从未被调用」的死键检查会误伤仅供外部/动态调用的键，不做。
- 调用点不包 try/except 兜底：漏注册是错误，由测试在合入前拦截，不由运行时吞掉。

## Consequences

- 「真身在 mixin、门面忘转发」类事故在合入前被测试拦下，不再依赖生产 AttributeError 事后取证，派发不再因漏注册整轮回滚烧预算。
- 新增门面调用点的实现空间受约束：注册、显式定义、显式豁免三者必居其一；豁免名单变更须附注释理由，属持续维护成本。
- AST 扫描对动态形态不可见：`getattr(self._pm, 名, default)` 字面量探测与 fail-soft try/except 子对象探测不入扫描面，该边界在契约测试注释中书面声明；新探测形态出现时须补豁免或纳入扫描。
