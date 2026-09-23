# design：fix-pm-facade-drift-forwarder-contract

## Context

- 门面转发机制：PMEngine._FORWARDER_REGISTRY（core/pm_engine/engine.py:217，类属性 dict，条目形态 "门面方法名": ("子对象属性名", "目标方法名")），消费在 __getattr__（:321-335，未命中 raise AttributeError）；_dispatcher 等 Lazy property（:3559-3569）构造 Dispatcher（core/pm_engine/dispatch/__init__.py:45-51，混入 VAdjudicationMixin 等）。
- 事故链：queue.py:34 QQQueueMixin 以 self._pm = pm（门面回引，:37-38）持有门面；:1267-1269 调 self._pm._preclassify_drift 五参；真身在 core/pm_engine/dispatch/adjudication.py:1068。缺注册 → __getattr__ 抛 AttributeError → 函数级 try（queue.py:1795-1800）兜住 → _rollback_failed_dispatch 整轮回滚 + retryable 重派。
- 前科：STATE.md:3115 _disputed_deliverables 同型事故（现已注册 engine.py:263）。
- 全仓三张同构注册表：PMEngine（engine.py:217）、AgentRunner（runner.py:432）、VerificationPipeline（pipeline.py:263）；pipeline.py:356 注释明确「静态式转发（5 个，首参非 pipe）MUST NOT 入表」。
- tests/test_code_fix.py:1335 现有断言只覆盖 AgentRunner 注册表的单名存在性；PMEngine 注册表零断言。

## Goals / Non-Goals

**Goals**

1. 漂移预分类通道恢复生产可达（一行注册）。
2. 「门面调用点必须可解析」成为测试硬门，终结「真身在 mixin、门面忘转发」类事故的复发。

**Non-Goals**

1. 不改门面转发机制本身（__getattr__/注册表结构保持）。
2. 不给调用点包 try/except（漏注册是错误，应被测试拦住而非被运行时吞掉）。
3. 不强行机械化验证全部三张表的每个调用面（VerificationPipeline 的静态式转发按豁免处理，书面说明）。

## 设计决策

- **D1｜AST 扫描而非运行时枚举**：`self._pm.<name>` 调用点是静态字面量，AST（ast.Attribute 链）可全量枚举且无导入副作用；运行时 dir() 枚举会因惰性 property 触发构造，误伤面大。
- **D2｜解析域 = 注册表键 ∪ 显式定义，豁免显式声明**：仅对注册表键做差集必自伤（显式方法与 pipeline 的 5 个静态式转发名合法不入表）；豁免清单以「门面类与混入类上显式定义的名字」自动推导为主、显式名单为辅，推导逻辑写进测试并在失败信息中给出归属（注册表/显式/豁免）。
- **D3｜反向断言查悬空而非查死键**：「无死项（键从未被调用）」会误伤仅供外部/动态调用的键；改为断言每条目 (sub_attr, meth) 可解析（getattr 链），这是悬空条目的精确定义且无误报面。
- **D4｜注册位置与风格**：紧跟 engine.py:265 的 _preclassify_orphan 之后，键值形态逐字对齐现有条目，保持裁决组相邻可读。

## 风险

- AST 扫描对动态拼装调用（getattr(self._pm, name)）不可见：现状生产代码无此形态（核查确认），契约测试注释中声明该边界。
- 豁免推导过宽会把真缺口豁免掉：失败信息输出归属分类，评审时可辨；豁免显式名单变更须经测试内注释说明理由。
