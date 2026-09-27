# ADR-083：drafted 晋升门控单点化，晋升核心三通道共享

date: 2026-09-14
status: accepted

## Context

drafted→ready 晋升有多条触发路径（事件、定时到期唤起、full_scan recovery、外部写入）全部汇聚到 PMEngine 同一入口。配置化人工晋升（`gates.promote_mode`）若在各调用方分支判断，未来新增触发路径易漏；CLI/dashboard 若各自复制「软化 + lint」组合逻辑，会随 lint 规则演进漂移——双实现曾在仓库造成治理事故。

## Decision

- 门控判定收敛在晋升入口单点（manual 时记 info 日志直接 return），全部既有触发路径与未来路径天然全覆盖，无需改动任何调用方。
- 晋升核心（软化含 dispute 审计 + lint + 违规写 error）提取为共享纯函数，daemon/dashboard/CLI 三通道调用同一实现；transition 收尾留调用方——PMEngine 通道进程内即时排队，外部通道依赖 watcher/full_scan 感知，共享函数保持「软化+lint+判定」的无派发副作用纯语义。
- manual 等待是设计行为，不写 STATE error：error 会触发 UI 告警与重派重试语义，「等待人工放行」写 error 会造成误报噪声与 recovery 误动作。
- 人工放行与自动晋升共享同一晋升语义；配置键与 `gates.approve_mode` 同段同构（auto 缺省零迁移），设置页同面板同构单选。

## Consequences

- lint 规则演进单点生效，双实现漂移面关闭；manual 下 drafted 期不再预 lint，违规在人工放行时仍完整拦截（拦截点后移但不消失）。
- 外部通道（dashboard 按钮 / CLI）操作 STATE.md 与 daemon 并发写竞态沿用既有文件锁与幂等防御（非 drafted 拒绝）；daemon 感知延迟依赖既有 watcher + full_scan，不新增跨进程请求文件类型。
- 人工操作类 CLI 子命令自此有独立入口（`bin/` 下 `fenix_*` 命名），不挂 daemon 主程序。
