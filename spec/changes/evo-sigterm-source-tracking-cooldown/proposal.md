# Proposal: sigterm-source-tracking-cooldown

## Why

agent_runner 对 CLI 子进程 SIGTERM 死法（Exit 143）与 SIGKILL 死法（Exit -9）除 daemon 关停场景（[shutdown-interrupted] 守卫）外一律归 [provider-transient] 走原地重试：无信号来源记录、无告警、反复撞运气直至 attempt 预算耗尽 frozen。2026-09-16 两个 admin 处置 run 全部被信号杀死（admin-refactor-dashboard-data-module-1789511370 Exit 143、admin-refactor-agent-runner-module-1789520256 Exit -9），无 cost 无根因；run 内 [provider-transient] 计数 27/12 而 [shutdown-interrupted] 为 0。已合入的 evo-run-failure-classification-circuitbreaker（819d8e85/ecbf6529）只覆盖 review run 失败三级分类，不覆盖 agent_runner CLI 子进程退出归类。产物硬门格式拒绝也被注入 [provider-transient]（同主题瞬态误标）。

## What Changes

- 记录 SIGTERM/SIGKILL 来源（daemon drain / 外部 kill / 资源回收 / 未知），143/-9 不再是无根因标签，run 错误信息与告警 evidence 透出来源。
- 143/-9 类失败连续出现触发熔断冷却（或 attempt 级硬失败），而非无限瞬态重试（复用/扩展 infra 熔断计数）。
- daemon 存活期内的框架主动终止（drain 关停 / cancel / supervision 超时强杀）全部留痕可判定归属，避免误归 provider-transient（daemon 已死的硬杀场景 runner 代码不执行、无归类动作，由读侧清扫补写终态，不在本方案范围）。
- 与产物硬门失败共享同一改法：非内容/非网关质量失败不记全局瞬断指纹通道（任务完成度类另去 [provider-transient] 标签；结构类保留既有原地退避恢复路径但停止指纹记账）。

## 非目标

- 不改变既有 4xx/切换类熔断语义。
- 不改变 provider 正常瞬态（网络抖动）的退避重试。
- 不改 review 层熔断（circuitbreaker 已覆盖）。