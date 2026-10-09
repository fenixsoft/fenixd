# v2 dev-server 生命周期治理
<!-- knowledge: capability=v2-devserver-lifecycle rev=1 sources=spec/archive/2026-10-10-evo-fix-v2-devserver-fallback-attribution -->

per-run v2 dev-server（被测服务进程）的归因标记、孤儿清扫判定与遗留收割：在服 run 的服务不误报不误杀，无主进程不永久占用端口。

## 规则

- 回退形态可归因：非框架目标项目（git 无 core/dashboard）走主树静态根回退形态启动的 dev-server 携带可归因的 worktree 路径标记，孤儿清扫的既有豁免逻辑（worktree 活跃引用判定）能识别其在服状态；run 在飞期间清扫周期不产生 skip 告警，进程受豁免保护直至 run 结束。归因标记落地双管：
  - argv 附加：标记 token 追加在 argv **尾部**（形态 `<worktree>/core/dashboard/static`，与 static-root token 的权威归属判据对齐）；不得前插——dev-server.mjs 按位置读 argv[2]=static_root、argv[3]=port，前插会改变语义。
  - worktree 软链：worktree 创建时补 core/dashboard/static 软链以消除回退形态本身；软链失败静默降级（不阻塞 create），降级后由归因标记＋记账兜底。
- 清扫告警按 pid 记账：orphan sweep 对不可归因进程按 pid 记账——首见告警一次、后续周期静默计数；记账为 daemon 进程内状态（重启即失，重启后按新进程重放一次首见告警）。升级人工或处置判定以「无引用进程」为前提，禁止按裸存活时长自动 kill（在服 run 可合法持有数小时）。扫描面按项目收窄，双 daemon 主机不互刷。
- 告警文案与处置安全：skip 告警不给出无条件「可手动 kill」建议，文案与归因/引用判定联动，说明判定局限与误杀在服 run 的风险。
- 重启后无主收口：daemon 重启后启动清扫对遗留 dev-server 对账——按登记/argv 标记区分有主与无主，可归因或有引用的保留，仅收割无主进程，防止端口池永久缩水。

## 关键行为

- 归因标记不引入 worktree 锁误判：锁存活探测以 is_claude_process 过滤进程类型，dev-server 不入锚；正常形态 dev-server 的 static-root token 本就含 worktree 路径，两种形态语义一致。

## 溯源

- 2026-10-10 evo-fix-v2-devserver-fallback-attribution（spec/archive/2026-10-10-evo-fix-v2-devserver-fallback-attribution） — 新增本页：回退形态归因双管（argv 尾部标记＋worktree 软链）、清扫按 pid 记账去重、告警文案纠偏、daemon 重启无主对账收割
