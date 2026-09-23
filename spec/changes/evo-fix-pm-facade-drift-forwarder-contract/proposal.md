# proposal：fix-pm-facade-drift-forwarder-contract

## Why

交付物争议的漂移预分类通道在生产上不可达：唯一生产调用点 core/pm_engine/dispatch/queue.py:1267-1269 经 self._pm 走 PMEngine 门面，而门面转发注册表 _FORWARDER_REGISTRY（core/pm_engine/engine.py:217-319）未登记 _preclassify_drift，__getattr__（engine.py:321-335）查表未命中即抛 AttributeError——异常被 _run_agent_worker 函数级 try（queue.py:1795-1800）兜住后整轮派发回滚、retryable 退避重派，白烧 run 预算。AttributeError 原文在案（.fenix/STATE.md:8155，add-code-review-auto-fix 的 _last_dispatch_error）。

这是复发型缺口：同构前科 'PMEngine' object has no attribute '_disputed_deliverables' 已发生过一次（STATE.md:3115，该名现注册于 engine.py:263）。修复本体一行注册，但只有同时落「调用点覆盖性契约测试」才能终结「真身在 mixin 上、门面忘转发」这一类事故。

## What Changes

- **A｜补注册**：engine.py 的 _FORWARDER_REGISTRY 在 _preclassify_orphan 条目（:265）后补 "_preclassify_drift": ("_dispatcher", "_preclassify_drift")，保持裁决组相邻；漂移分支派发恢复可达。
- **B｜门面契约硬门**：新增 AST 契约测试——扫描 core/ 下全部 self._pm.<name> 字面调用点，断言每个 name 可经门面解析（注册表键 ∪ 门面显式属性，dunder 除外），失败输出缺失名与调用文件:行号；反向断言注册表每条目的 (sub_attr, meth) 在门面上可解析（无悬空条目）。MUST 显式豁免「静态式转发不入表」的名字（core/pm_engine/verification/pipeline.py:356 注释清单）与门面显式定义，防自伤误报；扫描域按目录分桶（core/pm_engine/** 归 PMEngine 门，core/agent_runner/** 归 AgentRunner 门），反向断言按各注册表条目形态适配（PMEngine 二元组 / VerificationPipeline 模块函数单值）。
- **C｜三张同构注册表同门**：AgentRunner（runner.py:433）与 VerificationPipeline（core/pm_engine/verification/pipeline.py:263）的同构检查一并纳入（调用点按目录分桶归各自门面、反向断言按条目形态适配），不为凑数制造误报。

**BREAKING**：无。新增一行注册与测试；运行时行为仅漂移分支从「必崩回滚」变「正常可用」。
