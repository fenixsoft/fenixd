# ADR-216：Dashboard 按需长任务固定受理-轮询异步范式，一次性 spawn 执行不入开发主链路

date: 2026-10-04
status: accepted

## Context

dashboard 侧出现「用户点按钮触发重活」类功能（回归草稿 autodraft、项目架构图 archify），单次耗时从分钟级到 30 分钟。autodraft 曾在 HTTP 线程内同步等待 900s——浏览器休眠、代理超时下该模式不可靠（与 CodeFixProgressCard 切后台冻结、SSE 长连接事故族同源）。同时框架已有完整的 agent run / 车道 / 预算机器，这类按需任务是否复用需要统一裁定，否则每个新功能各自选型。

## Decision

dashboard 触发的按需长任务一律采用「受理-轮询」异步范式：POST 端点只受理并立即返回，实际执行放在 daemon 后台线程；HTTP 线程不得同步等待任务完成。前端在执行期间以固定间隔轮询状态端点；任务状态经磁盘文件原子写持久化，页面刷新、重开标签不丢态，daemon 重启后的残留执行态由读侧合成为中断（不产生死态）。

执行载体是一次性 headless claude spawn（cwd=项目根、`start_new_session=True`、超时进程组击杀、env 剔除 agent-run 专用键），不进开发主链路：无 run 台账、无车道、无预算、无新增配置项（参数用模块常数）。需要 agent 侧技能（skill）时由 spawn 前检测 + 自动安装兜底，安装失败给人工命令。

## Consequences

- 分钟级任务的可靠性不再受 HTTP 请求生命周期约束；页面、标签、daemon 重启三个维度都不产生永久卡死的执行态。
- 这类任务对框架的调度、预算、观测面不可见：成本与并发治理依赖手动触发天然节流 + per-project 单飞 + 超时上限，运营侧排查时要意识到它们不走 run 体系。
- 后续同类 SPEC 的实现空间被约束：新增按需长任务不得引入同步 HTTP 等待，也不得为承载它去复用或扰动开发车道与预算体系。
