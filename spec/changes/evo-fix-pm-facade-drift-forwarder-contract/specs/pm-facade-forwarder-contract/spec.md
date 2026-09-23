# spec-pm-facade-forwarder-contract

## ADDED Requirements

### Requirement: 漂移预分类经门面可达

core/pm_engine/engine.py 的 _FORWARDER_REGISTRY MUST 登记 "_preclassify_drift" -> ("_dispatcher", "_preclassify_drift")，与 "_preclassify_orphan"（裁决组）相邻；PMEngine 实例上经 self._pm._preclassify_drift(...) 的调用 MUST 转发到 Dispatcher（VAdjudicationMixin）真身，交付物争议漂移分支派发 MUST NOT 再抛 AttributeError。

#### Scenario: 漂移分支派发可用

- **WHEN** 实现 run 对交付物缺件提出争议且命中漂移分支（queue.py 争议分支）
- **THEN** _preclassify_drift 正常执行并返回预分类结果，MUST NOT 出现整轮派发回滚

#### Scenario: 注册条目与真身一致

- **WHEN** 经门面调用 _preclassify_drift
- **THEN** 实际执行体是 Dispatcher._preclassify_drift（VAdjudicationMixin），签名与生产调用点五参形态一致

### Requirement: 门面调用点覆盖性契约硬门

新增契约测试 MUST 以 AST 扫描 core/ 下全部 self._pm.<name> 字面调用点，断言每个 name 可经 PMEngine 解析——解析域为「注册表键 ∪ 门面类显式定义的属性与方法」，dunder 与测试/注释除外；任一调用点不可解析即测试失败，失败信息 MUST 含缺失名字与调用文件:行号。反向 MUST 断言注册表每条目的 (sub_attr, meth) 可在门面上解析（惰性 property + getattr），无悬空条目。豁免机制 MUST 显式存在：静态式转发不入表的名字（core/pm_engine/pipeline.py 注释清单）与门面显式定义 MUST NOT 被误报。

#### Scenario: 新增漏注册调用点被硬门拦截

- **WHEN** core/ 下新增 self._pm.<未注册且未显式定义的名字> 调用点
- **THEN** 契约测试失败并输出该名字与调用文件:行号

#### Scenario: 悬空注册条目被反向断言拦截

- **WHEN** 注册表出现指向不存在子对象属性或方法的条目
- **THEN** 契约测试失败并输出条目键与目标

#### Scenario: 合法不入表名字不误报

- **WHEN** 调用点命中的是门面显式定义的方法或豁免清单中的静态式转发名
- **THEN** 契约测试通过

### Requirement: 同构注册表同门检查

AgentRunner（core/agent_runner/runner.py）与 VerificationPipeline（core/pm_engine/pipeline.py）的同构注册表 MUST 纳入同类检查（调用点前缀与解析域按各自门面适配）；适配 MUST 以「不制造误报」为界，无法机械化验证的面 MUST 书面说明而非强行断言。

#### Scenario: 三张注册表同规则守护

- **WHEN** 任一门面的调用点出现漏注册
- **THEN** 同一套契约测试发现并报告
