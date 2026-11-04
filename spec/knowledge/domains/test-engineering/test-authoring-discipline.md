# 测试编写设计规则

<!-- knowledge: capability=test-authoring-discipline rev=2
     sources=spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md,spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md -->

测试（尤其 agent 车道回归用例）编写时的隔离与替身设计纪律：进程级全局替换的复原义务、假进程替身的分发方式、常驻线程收割、用户级配置隔离与夹具路径指向。

## 规则

- 进程级全局替换必须 try/finally 复原：测试内替换 `subprocess.Popen` 这类进程级全局对象时，复原代码必须放 try/finally——裸写在用例尾部时，SIGALRM（10s 单用例硬门，见 per-test-timeout 页）会在复原前打断，全局泄漏后同场全部子进程用例连坐超时。普通 pytest 测试类没有 `addCleanup`（unittest 专属），不存在兜底通道。
- 假 spawn 按 `cmd[0]` 分发：劫持进程启动的测试替身按命令首元素分发——真实子进程命令直通、假命令返回 fake；不按调用序号或全局一刀切分发，避免用例间互相污染。
- watchdog/常驻线程类测试必须收割线程：触及 `CLAUDE_PID` watchdog 类常驻线程的用例须在用例边界收割线程（tests/conftest autouse 收割现行）。泄漏的 watchdog 线程盯 pytest 自身 pid，负载峰值窗口集体误判死亡并对自身发 SIGTERM 自杀——非确定性的整场回归失败形态。
- 用户级配置敏感测试双隔离：全局开关常开形态下，涉及用户级配置的测试以 `patch("core.config.USER_CONFIG_DIR")` + `patch("core.dashboard.data.USER_CONFIG_PATH")` 双点隔离（仓内既定模式），不触碰真实用户配置。
- 测试夹具与场景数据 MUST 指向 `spec/archive/`：指向 `spec/changes/<SPEC>` 的夹具在 SPEC 归档迁出时批量失效，成为 judge 噪音源。
- 单元测试禁读构建产物：单测 MUST NOT 依赖 gitignored 构建产物（dist）——裸 worktree 回归不含 gitignored 文件，依赖 dist 的用例每批首个回归必假失败；构建产物行为由构建级门禁（见 [build-gates 域](../build-gates/_domain.md)）承接，不进单元测试。

## 溯源

- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠测试编写设计规则五条：进程级全局替换 try/finally 复原义务（pytest 类无 addCleanup）、假 spawn 按 cmd[0] 分发、watchdog 常驻线程收割、用户级配置双隔离补丁模式、夹具路径指向 spec/archive
- 2026-11-04 memory-distill-diagnostic-signatures（spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md） — 折叠测试假失败判读签名：单元测试禁读 gitignored 构建产物（裸 worktree 回归缺 dist 即假失败），构建行为归构建级门禁
