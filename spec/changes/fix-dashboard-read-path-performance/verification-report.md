# 验证报告：fix-dashboard-read-path-performance

> ⚠️ 本报告由框架于 2026-09-17T00:35:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T00:35:15.142906+00:00

## 结论：✅ 通过（verified）

**状态：verified — 18/18 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 18/18 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 18 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.39M |
| 本链增量 Token（输出） | 0.15M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-incremental-single-change-recomputes-one | R1-S1.1 STATE 变化不触发全量重建：构造 3-spec 临时 fixture（复刻 tests/test_dashboard_index_incremental.py 的 make_project），首次 SummaryIndex.get 全量构建后仅改动 myspec 的 tasks.md（文件签名变化），spy 包装 core.dashboard.data.spec_summary 计数，断言本次 get 只重算 myspec 一个，其余 2 个命中缓存（增量失效语义：core/dashboard/data/summary.py:484 SummaryIndex / :542 _runs_by_spec_sigs）。 | pass | 0/4 | - |
| cli-incremental-equivalence-with-full-rebuild | R1-S1.2 缓存结果与全量重建等价：同一 STATE 快照上分别走增量路径（先 get 再 get，全命中缓存）与全量路径（fresh SummaryIndex 实例重建），断言两次产出的 spec 摘要集合逐条一致（spec.md Scenario：缓存结果与全量重建等价；delta 后 idx 保留与 fresh 构建必须产出相同结果）。 | pass | 0/4 | - |
| cli-incremental-entry-field-change-no-stale | R1-S1.3（关键）仅 STATE 条目字段变化也必须重算：依赖文件（tasks.md/.spec.yaml/specs/verify-progress/config.yaml）全未变，仅 STATE.md 中 myspec 条目 status 由 testing 改为 blocked（显式 bump mtime），断言第二次 get 重算该 spec 且摘要 status 反映新值，MUST NOT 返回陈旧摘要（_entry_fingerprint 并入 _spec_dep_sigs：core/dashboard/data/summary.py:419/436；spec.md 该条不可由等价性替代）。 | pass | 0/4 | - |
| cli-incremental-first-build-and-corrupt-rebuild | R1-S1.4 首次构建与损坏回退：fresh SummaryIndex 首次 get 全量构建（spy 计数 = 全部 spec 数）；随后向索引注入损坏条目（summary/sigs 缺失的假缓存），再次 get 断言被损坏 spec 经 per-spec 签名比对自然触发重建并返回正确摘要（全量重建仅用于 idx is None 或损坏：core/dashboard/data/summary.py:522-531）。 | pass | 0/4 | - |
| cli-runs-dir-single-glob-per-cycle | R2-S2.1 单轮只扫一次目录：多 spec fixture + runs 目录内多 run 产物，spy 包装 core.dashboard.data.summary._runs_by_spec_sigs（:364）计数，断言一次 SummaryIndex.get 中目录预扫描仅调用 1 次且服务全部 N 个 spec（目录 glob 次数为常数、不随 N 增长），再次 get（缓存命中）仍仅 1 次预扫描——spec_summary 经 runs_files 预选集入参、get_runs 预选文件集入口（core/dashboard/data/runs.py:181）不再逐 spec 重扫目录。 | pass | 0/4 | - |
| cli-tail-read-big-file-window-bytes | R3-S3.1 大文件尾读不全读：构造 12MB run 文件（400×30KB 行 + 末 3 短行，超 _READ_RUN_TAIL_WINDOW=64KB），spy Path.open 的 f.read 累计字节量，断言读取字节 ≤ 窗口（行长未超窗时不走全读），且 _read_run_lines 结果与逐行全读参考实现逐条等价、classify_run 判定一致（core/dashboard/data/runs.py:258 窗口常量 / :293 _read_run_lines）。 | pass | 0/4 | - |
| cli-tail-read-overlong-last-line-fallback | R3-S3.2 超长末行回退且不误判：末行 200KB 超过字节窗口（result 事件携带大 payload），断言 _read_run_lines 回退全量读取、结果与逐行全读参考实现等价，classify_run 判定 done 而非 running（MUST NOT 从行中间截断导致已完成 run 误判 running：core/dashboard/data/runs.py:293-320）。 | pass | 0/4 | - |
| cli-retention-terminal-run-archived | R4-S4.1 终态 run 被归档：临时 fixture .fenix/runs 下放终态 run（result:done 事件）与运行中 run（assistant 行），调用 core.dashboard.data.runs_retention_check，断言返回 moved=1、终态产物从 runs/ 移入 runs/archive/、运行中 run 不被误移（活跃目录有界性由「终态即移出」保证：core/dashboard/data/runs.py:661）。 | pass | 0/4 | - |
| cli-retention-archive-cleanup-by-limit | R4-S4.2 归档按上限清理：fixture archive/ 下放 5 个 jsonl（mtime 升序），config runs.keep=2 调用 runs_retention_check，断言 deleted=3、archive_total 降至 2、deleted_names 为最旧 3 个条目（按 mtime 升序删除：core/dashboard/data/runs.py:676-696）。 | pass | 0/4 | - |
| cli-retention-cleanup-observable-log | R4-S4.3 清理动作可观测：传入收集型假 logger（对齐 fenixd Logger info/warning 签名），构造归档超限 fixture 跑 runs_retention_check，断言日志含「删除归档产物」行且携带具体文件名（可追溯）、并含「终态 run 移入归档」行；单轮删除量受 _RETENTION_DELETE_PER_CYCLE_MAX 批次上限约束、不静默大批量删除（core/dashboard/data/runs.py:609-616 / :688）。 | pass | 0/4 | - |
| cli-retention-watcher-comment-consistent | R4-S4.4 注释与实现一致：读取 core/dashboard/watcher.py 中 runs 保留相关注释（:27-28「终态即移出/归档受 runs.keep 上限约束缺省 50」），断言注释描述与 _RETENTION_KEEP_DEFAULT=50（core/dashboard/data/runs.py:611）及「终态移入归档」实现行为一致（spec.md Scenario：注释与实现一致）。 | pass | 0/4 | - |
| cli-retention-archived-run-readable-read-path | R4 读路径消费归档 run：fixture runs/archive 放一条终态 run 产物，断言 get_runs(include_archive=True)（core/dashboard/data/runs.py:181）返回含归档条目，且 spec_detail 的 runs 历史字段包含归档 run（spec_detail 读路径 core/dashboard/data/summary.py:625-626 含归档回看），归档 run 被清理/归档后 spec 时间轴与运行历史仍可回看。 | pass | 0/4 | - |
| cli-retention-keep-default-and-invalid-fallback | R4 上限语义：runs.keep 缺省 50、缺失/非法值（abc/0/-1）均回退缺省 50，且上限约束的是归档目录条目数（_resolve_runs_keep：core/dashboard/data/runs.py:618-632 / 缺省 _RETENTION_KEEP_DEFAULT=50 runs.py:611）。 | pass | 0/4 | - |
| api-overview-structure-latency | 读路径端点回归：GET /api/overview（core/dashboard/server.py:374）返回 200、Content-Type application/json、响应为含 projects 数组的对象（跨项目状态统计聚合 spec 摘要索引），latency_under 3000ms（spec 预期 <100ms 量级，验证环境留启发式宽松阈值）。URL origin 由框架改写到本次实例。 | pass | 0/5 | - |
| api-specs-structure-latency | 读路径端点回归：GET /api/specs?project=fenixd（core/dashboard/server.py:376）返回 200、{project, specs} 结构、specs 首项含 status 字段（spec_summary 输出由 SummaryIndex 缓存/增量失效驱动），latency_under 3000ms（spec 预期冷路径消除秒级卡顿）。URL origin 由框架改写到本次实例。 | pass | 0/4 | - |
| web-overview-page-renders | 概览页读路径回归：打开 Dashboard 概览页 #/overview（SPA hash 路由，菜单项 app.tsx:101；页面标题组件 core/dashboard/static/src/pages/overview/index.tsx:65「跨项目概览」），页头 .ant-page-header 可见、标题文本正确、无控制台错误——概览页聚合全部项目 spec 摘要，是读路径（SummaryIndex 增量失效 + 去 glob）在真实项目数据上的整体回归。 | pass | 0/3 | - |
| web-project-specs-table-renders | 项目 spec 表格回归：打开项目详情页 #/projects/fenixd（SPA hash 路由，动态二级菜单 app.tsx:107），桌面视口渲染 antd Table（core/dashboard/static/src/pages/projects/list.tsx:744 起 columns/Table，状态列渲染 statusMeta Badge），断言表格容器可见、含 spec 行、无控制台错误——spec 摘要列表由 /api/specs 驱动，验证增量失效后的列表读路径在真实项目上正常。 | pass | 0/3 | - |
| api-specs-repeat-requests-stable | 读路径缓存稳定：连续两次 GET /api/specs?project=fenixd（server.py:376，SummaryIndex 缓存命中路径）均返回 200 且 project 一致、响应体含 specs 键——增量失效后读路径稳定、STATE 未变时不触发重算（回归点：操作后状态与操作前对比）。URL origin 由框架改写到本次实例。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 18 个（第 1 轮）。

首轮写入 18 个场景

