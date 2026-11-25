# ADR-380：更新应用一律走平台化分离编排进程

date: 2026-11-25
status: accepted

## Context

框架一键更新的编排链是「下载→校验→staging→停全部服务化进程→换装→起服务→状态落盘」的分钟级长时序事务，其中停步必然覆盖 daemon 与 dashboard 自身——任何在 daemon/dashboard 进程内执行更新应用的编排者，都会在停步中杀死自己（自杀前交接协议的复杂度与中断面远超收益）。编排也不能挂在 HTTP 请求生命周期上：换装分钟级，请求超时后进度不可见、触发方重启即蒸发。多项目部署下同一框架安装上的各 daemon 都可能触发更新，还需并发互斥。

## Decision

1. 更新应用 MUST NOT 由 daemon 或 dashboard 进程内执行：触发方（dashboard API / CLI / 任何后续新增入口）spawn 一个平台化分离的短命编排进程（POSIX setsid + double-fork；Windows DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP），触发方即时返回「已受理」。
2. 编排进程独立完成全链，每阶段进度与终态写框架级 `~/.fenix/update/status.json`；UI/CLI 轮询读状态文件获取进度，不依赖编排进程存活。
3. 并发触发以框架级 `~/.fenix/update/apply.lock` 互斥（O_EXCL + 陈锁清扫，2 小时兜底），第二触发者得到 409。
4. daemon 在更新场景只承载周期检查与状态呈现，应用链完全旁路；后续新增任何更新触发入口必须走同一分离编排，禁止进程内自换装。

## Consequences

- 触发方进程关闭/重启不中断进行中的更新；dashboard 自身被换装重置不再带来编排半途蒸发面。
- 状态可见性完全依赖 status.json 落盘纪律：编排必须每阶段落盘，漏落盘即 UI 盲区。
- 编排失败无法经 HTTP 直接回传，只能经状态文件与审计留痕透出，排障入口前移到状态/审计文件。
- 分离进程引入幂等恢复义务：编排进程自身可能中断，残留 staging/.old 态须由下一次编排按状态续走或回滚（与 ADR-381 的换装状态机配套）。
