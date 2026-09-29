# 增量数据 Watcher

<!-- knowledge: capability=dashboard-incremental-watcher rev=1
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data -->

dashboard 侧的文件监视与广播通道：目录签名跳层监视 + 增量（diff）`state` 事件广播。

## 规则

- `state` 事件为增量形态：`{type:"state", project, specs:[{spec, summary}...], overview:null, details:{spec: detail}}`；`specs` 仅含变更 spec 的摘要（新增/修改入列，删除以 `summary:null` 标记），`details` 仅含变更 spec 的详情；不全量下发 specs+details+overview。单 spec 变更只推单条；日志追加等无 spec 文件变化的轮次，广播 payload 为 KB 级小包。
- 两级目录签名跳层：每项目每轮先 stat 顶层数据源集合（`STATE.md`、`spec/changes`、`.fenix/logs`、`.fenix/runs`、`.fenix/verify-progress`、`.fenix/admin_alerts.json`），目录签名 `(mtime_ns, size, ctime_ns)` 未变则跳过整棵子树；spec 目录级同样签名跳层，签名未变不做该 spec 的文件级 stat。
- 规模目标：单轮 stat 数与 spec 数解耦（每轮 stat 数 = O(顶层数据源 + spec 目录数)），spec 目录级 stat 走页缓存；项目文件全部无变化时，一轮 scan_once 除顶层 stat 外不发生任何 spec/changes 内文件级遍历；文件变更在 ≤2 个扫描周期内被检测并触发增量广播。
- 零新增依赖：不引入 watchdog 等第三方文件监视库，签名跳层用标准库 stat 实现。

## 溯源

- [2026-09-09 2026-09-09-add-dashboard-incremental-data](spec/archive/2026-09-09-add-dashboard-incremental-data/) — watcher 由「日志一变即全量重组广播」改为增量 diff 广播 + 目录级签名跳层监视，广播 payload 从 ~100KB/次降至 KB 级
