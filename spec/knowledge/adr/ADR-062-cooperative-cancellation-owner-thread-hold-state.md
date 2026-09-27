# ADR-062：人工取消 = 属主线程协作式终止 + 状态机解耦（hold-state）

date: 2026-09-10
status: accepted

## Context

run 执行链位于 daemon 进程内（worker 线程 + CLI 子进程），run 失败的通用路径会触发重试与自动重派——管理员的取消若被当作普通失败，会被自动重派立即抵消。跨线程直接 kill 会破坏「result 终态行必须是 run 产物文件最后一行」的契约，并让超时/监督/取消多种终止来源的异常分类在 kill 方与属主线程间扯皮。

## Decision

- **协作式终止**：取消入口只做 run_id 归一化（剥 attempt 后缀，旗标键恒为基础 run_id）+ 旗标登记后立即返回；终止动作由**属主线程**在轮询环与 attempt 间隙检查点执行（SIGTERM → 有界宽限 → kill → 追加 `cancelled` 终态行）。全部收尾留在属主线程序。
- **专用取消异常**在通用 Exception 处理之前单独捕获：不重试、不退避、不触发 provider 切换——异常类型是绕开自动失败行为的唯一可靠分叉点。
- **取消不做任何状态转换**（hold-state）：只写 error 说明、不翻状态、不动重试/熔断记账、不入队；spec 停留原态，由 stuck 检测/恢复扫描按既有节奏接管。自动链路（recovery/stuck/gate/freeze）无权调用取消。
- run 产物终态行三分类型：`cancelled`（人工）/ `interrupted`（框架关停）/ `error`，分类直读不复用。
- 跨进程入口走文件信号，镜像 admin_invoke 模式：tmp+rename 原子写、消费即删、损坏即删、未消费时冲突拒绝（天然节流）；受理落 minor 级审计记录。

## Consequences

- 取消受理到实际终止延迟 ≤ 2 个轮询周期（秒级），对人工操作无害。
- 取消后 spec 滞留原态是特性：永久停止用 freeze、放行则不动——取消不越权替管理员做状态决策。
- 旗标登记与 run 自然收尾竞态无害：取消只在未来检查点生效，收尾即清旗标。
