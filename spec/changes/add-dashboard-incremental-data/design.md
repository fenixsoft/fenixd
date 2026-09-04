# Design: Add Dashboard Incremental Data

## Context

Dashboard 数据管线现状（150 spec 实测）：

- **数据源**：STATE.md（56KB 文本，10000 spec 时 ~5MB）、`openspec/changes/<spec>/`（tasks.md + specs/*.md + verification-report.md）、`.fenix/`（runs/*.jsonl 累计 11MB、verify-progress/、logs/fenixd.log 7.5MB 且 daemon 活跃时持续追加）。
- **读侧**：`/api/specs` 每请求对全部 spec 跑 `spec_summary()`——6 次独立磁盘 IO（get_runs glob、count_scenarios rglob、parse_tasks 读 tasks.md、read_spec_mode 开 `.openspec.yaml` 走 YAML 解析、is_spec_archived、parse_verify_progress）。cProfile：109 spec 冷启动 44ms，其中 42 次 YAML safe_load、29ms 花在 get_runs。
- **广播侧**：watcher 每 1s 全量枚举项目文件（`_iter_project_files` 对每 spec yield 5~8 个路径并 stat），随后日志一变化就 `_handle_state_change` 全量重组 overview+specs+details 广播。
- **订阅侧**：前端 2s 固定轮询三端点 + SSE 双通道叠加。
- 现有缓存先例：`_RUN_TASK_CACHE`（run 文件 mtime+size 键，上限 64 清空）已验证「签名键 + 有界缓存」模式可行。

## Goals / Non-Goals

**Goals:**
- 热路径（浏览 dashboard 时的 API 与广播）从 O(N) 每请求全量重算变为「启动一次构建 + O(变更) 增量」。
- 150 spec 轮询路径 CPU 降 ~95%；10000 spec 时 `/api/specs` 有界 <300ms（索引读；分页留给后续）。
- 广播 payload 从 ~100KB/次 降至 ~1KB/次（diff 只带变更 spec）。
- 保持 D2 零新增依赖，保持 SSE/API 对外契约形变兼容。
- 10000 spec 时 watcher 每轮 stat 从 7 万次降至 O(目录数)。

**Non-Goals:**
- 不做数据库/SQLite 持久化索引（后续规模化里程碑）。
- 不做 inotify/watchdog（用户决策：保 D2，选目录级签名轮询）。
- 不做虚拟滚动/服务端分页（前端列表 DOM 上限留给后续 SPEC）。
- 不改变 STATE.md / tasks.md / run 产物等数据源格式。

## Decisions

### D1 摘要索引的归属与生命周期（server 内存态）

- 索引持有在 `DashboardHTTPServer` 实例上（`self.summary_index`），watcher 与 `_handle_api` 共享同一实例 —— 单一写者（watcher 线程）、读者（HTTP 线程）经 `threading.Lock`（读写锁语义，读多写少用 `RLock` 即可；简单场景用 Lock 包整段替换也接受）。
- 结构：`{project_name: {spec_name: summary_dict}}`；每项目一个 `summary_index[proj]` 派生自 `parse_state(proot)` 的快照 + 每 spec 的摘要缓存失效键 `{path → (mtime_ns, size)}`。
- **失效策略**：每 spec 记录其依赖文件签名集合（tasks.md / specs 目录 / .openspec.yaml / runs 目录 + verify-progress 相关文件）。任何请求路径下先比对签名，变化则只重算该 spec 的 `spec_summary`；`STATE.md` 自身签名变化 → 全量重建该项目的索引（新增/删除 spec 只有 parse_state 全量才能发现——增量解析只识别变更，不识别增删，故全量重建的触发仅限 STATE.md，频率低）。
- **构建时机**：首次 `/api/projects` 或 watcher 首轮扫描时惰性构建；构建并发安全（单例 + lock）。
- **有界性**：索引常驻内存（10000 spec 的摘要 dict ≈ 数十 MB，可接受）；签名缓存不入内存上限约束——签名只对存在路径记录。

### D2 watcher 增量协议的形变

- 保持 `{type: "state", project, overview, specs, details}` 结构，但引入**增量形态**：任何字段可为 `null` 表示「无变化不推送」；`specs` 改为 `[{spec, summary}...]` 仅列变更条目；`details` 仅为变更 spec 的详情。
- **兼容**：旧前端（若存在）对 null 语义无感知——但当前 v3 前端唯一消费方与本次改动同步发布（dist 重建），因此：增量形态仅在新前端启用，旧格式全量推送作为失败降级（`mode` 协商：新前端握手带 `Accept-Version: incremental` 头 —— 简化：直接统一改，dist 随 SPEC 同仓提交，无旧客户端存活）。
- 简化决策：**直接统一为增量语义**，不再全量兜底。理由：v3 SPA 是唯一消费方且同仓发布；增量广播时前端本就注册的轮询兜底心跳会补全任何丢帧窗口。
- `overview` 字段：watcher 不再逐次全量重算 overview；改为 `{changed_total_delta}` 语义不可行（overview 是多项目聚合，任何 spec 摘要变化都会改变它）→ **决策：overview 由前端在收到增量事件后以 30s 间隔合并计算**。即 watcher 完全不下发 overview，`state` 事件只含 `{spec, summary}` 增量；前端本地维护 spec 摘要集合并自算统计。此为 D3。

### D3 前端本地归并（去重核心）

- v3 前端维护**本地 spec 摘要表**（`Map<spec_name, summary>`）：首屏经 `/api/specs` 全量拉取建立；此后 `state` 增量事件进入 patch 队列（去重：同 spec 1s 内多次事件只应用最新）。
- 统计（status 分布、task 汇总、badges）由本地表推导，30s 心跳时以 `/api/overview` 校准一次（overview 仍全量返回，频率低了 15 倍，成本可接受），`visibilitychange` 时立即校准。
- 2s 轮询 → **30s 心跳**（对齐 watcher 心跳间隔）+ visibility 补刷 + SSE 增量为准。
- spec 表格：按 `created` 排序的本地表直接驱动渲染；行更新只重绘该行（React 已有 key 机制，天然 patch）。

### D4 配置解析缓存（无失效风险面）

- `read_effective_config` / `read_spec_mode` 增加 `functools.lru_cache`-风格签名缓存：`key=(resolved_path, mtime_ns, size)`；缓存无上限风险（键 ∈ {用户级 config.yaml，项目 config.yaml，每 spec .openspec.yaml}，规模与 spec 数线性，10000 时 ~10001 条目，可接受）。
- 写路径（`write_config` / 变更 `.openspec.yaml` 的流程）必须显式 `cache_clear` 该路径键 —— 写后 mtime 已变，签名键自然失效，无需显式失效。**决策：依赖签名键自然失效，不维护写侧钩子**（与 `_RUN_TASK_CACHE` 一致，规避钩子遗漏 bug）。
- `cleanup_runs`：增加项目级节流 `(last_ts)` —— ≥60s 才实际执行；返回永远幂等。

### D5 日志偏移索引

- 每日志文件 `fenixd.log` 维护 `.fenix/logs/.idx/fenixd.log.offsets`（JSON：`{"size": N, "offsets": [每 64KB 块首行字节偏移...]}`）。
- 查询（`get_spec_timeline` / `get_recent_events`）：由目标时间窗口起点定位块索引 → 只读对应块段（最大 1MB 窗口内 16 个块）。窗口外（> 最近 1MB）直接返回空/截断——时间轴按最近活动截断展示（design 决策：历史窗口对 Dashboard 用途足够）。
- 每次查询后追加更新块索引（`size >= 记录 size` 时才写，写拍卖给最后块 ± 追加）。
- 失效/损坏：索引缺失或 size 不匹配 → 重建索引（仅扫描一次）并继续。

### D6 连接上限

- `SSEHub.register()` 加计数：活跃连接 ≥32 → 拒绝（`_handle_sse` 直接 503 返回 JSON 错误体，客户端退化为轮询）。
- `ThreadingHTTPServer` 子类统计 `threading.active_count()` ≥ 上限(64) 时响应 503 `{"error":"server busy"}`（在 `_handle` 入口判断）。
- 上限可配置常量（模块级），不做配置项（避免为一次性治理引入配置面）。

### D7 watcher 目录级签名跳层（替代 inotify）

- `_iter_project_files` 改为两级：
  1. **顶层数据源签名**：每项目 stat 固定集合（STATE.md、openspec/changes、.fenix/logs、.fenix/runs、.fenix/verify-progress、.fenix/admin_alerts.json）——8 次 stat。
  2. 仅当目录签名变化时进入 **spec 目录枚举**：stat `changes/` 下全部 spec 目录（10000 个 → 10000 次 stat，页缓存 ≈10ms，可接受），再对签名变化的 spec 目录做文件级签名比对（原 7 文件集合）。
- 目录签名 =（mtime_ns, size, ctime_ns）；文件内容修改会更新文件与父目录 mtime；`touch` 保时间场景在本工作流不存在（全部写入走正常 open/write）。
- 清理语义保持：删除的目录从签名表剔除。

## Risks / Trade-offs

- **索引与真实文件漂移**：摘要签名的 6 个依赖文件覆盖不全（如 `read_spec_mode` 读的 `.openspec.yaml` 未在签名集合）→ 摘要过期。缓解：签名集合与 `spec_summary` 的实际读路径逐一对齐（实现任务必须列全依赖文件），并对「保守失效」倾斜——把 specs/ 目录整体纳入签名。
- **增量广播丢帧**：SSE 队列满丢弃旧事件（256 上限现状）+ 增量语义下中间态丢失 → 前端心跳兜底（30s overview 校准 / 1s 队列上抛时本地表以 overview 修正）。
- **全量重建风暴**：parse_state 每轮全量解析单点仍存在（10000 spec 5MB/次），但已从「每请求」降到「STATE.md 每变更一次 + 每次首建」。
- **格式迁移**：`state` 事件增量形态与旧字段冲突 —— 已决策无旧客户端，风险封闭。
- **10000 spec 边界**：评论区无虚拟滚动/分页仍会卡 DOM —— 明确 Non-Goal，列表上限留给后续 SPEC（索引化后分页是纯前端+查询参数工作）。
- 页面长时间挂机（>30s 无事件）后 spec 表格的 created 排序漂移：前向排序由本地表维护，心跳校准保序。