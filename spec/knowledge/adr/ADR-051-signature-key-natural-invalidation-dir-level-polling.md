# ADR-051：变更检测纪律——签名键自然失效，目录级签名两级轮询

date: 2026-09-09
status: accepted

## Context

配置与 spec 模式解析每请求重读磁盘；watcher 每轮对每 spec stat 5~8 个文件（万级 spec 时 7 万次 stat/轮）。既有 `_RUN_TASK_CACHE` 已验证「签名键 + 有界缓存」模式可行。引入 inotify/watchdog 会破坏零新增依赖约束。

## Decision

- 读缓存键 = 路径签名 `(resolved_path, mtime_ns, size)`：命中即免读，写后 mtime/size 自然变化使键失效。依赖签名键自然失效，不维护写侧显式失效钩子——写侧钩子协议的遗漏点是已实证的 bug 形态，自然失效不需要任何写侧配合；缓存规模与受管路径数线性，可接受常驻。
- watcher 变更检测改目录级签名两级跳层：顶层每项目 stat 固定数据源集合（个位数次 stat），目录签名不变则整目录跳过；仅签名变化的目录进入 spec 级文件签名比对。目录签名 = (mtime_ns, size, ctime_ns)，本工作流全部写入走正常 open/write，无 touch 保时间场景。
- 清理语义保持：消失的目录从签名表剔除；周期性清理任务加项目级节流，返回幂等。

## Consequences

- 万级 spec 的每轮 stat 从 O(spec×文件数) 降至 O(目录数)；新增读缓存必须走签名键模式，不得引入需要写侧配合的失效协议。
- 签名集合漏文件会导致摘要过期，失效向保守倾斜是纪律（宁可多算不可陈旧）；保持零新增依赖，不用 inotify。
