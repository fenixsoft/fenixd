# 设计：lint 一次全报 + tasks.md 文件监视即时唤醒

## 现状（已回源）

- lint 短路结构：core/deliverables.py :3227/:3234/:3246 三个正则；_tasks_parse_counts（:3249）的 unnumbered 只在 in_group 语境收集——分组未解析时全部 checkbox 行都在语境外，缺编号检查结构性空集，但 item_count（全量 checkbox 计数）恒可测。
- lint_tasks_text（:3293）三段互斥早退：:3329 分组违规 return → :3335 零任务行 return → :3344 缺编号 return → :3361 归属段；ownership_violations_for_tasks_text 已独立成函数（tests/test_task_artifact_ownership.py 5.4 零误拦守卫要求归属面不受可解析性短路吞并）。
- 调用方：core/pm_engine/promotion.py:163-183 已把三类 lint（deliverables/tasks/title）违规全量聚合进一条日志（"；".join）——「一次一报」只在 tasks.md 族内部，调用方聚合已兼容多条字符串。
- 监视与恢复：core/event_bus.py _watch_loop（:1062）2 秒一轮只对 STATE.md 做 checksum，变化才 _dispatch_changes；恢复节拍 _periodic_scan_loop → _run_full_scan_body（:318）→ _recover_one（:392）→ drafted 分支（:412-413）logger.info("Recovery: re-triggering promote…") + pm_engine.handle_event("spec_drafted", name, entry)。
- 触发链：handle_event("spec_drafted") → core/pm_engine/engine.py:582 handler 表 → :600 _on_spec_drafted（start_after 门控 :614-637 与 promote_mode manual 短路）→ promotion.py:11 promote_drafted。
- 先例：_dispatch_changes:1365-1383「外部 →testing 跃迁即时派发」——watch 通道 diff 出事实即复用恢复出口、不等 30 分钟兜底。
- 无自激励环：_diff_specs（:1402-1487）只在新出现/status 变化时发事件，error 字段变化不发事件。
- 清错通道：core/dashboard/data/admin_actions.py:1529 clear_spec_error（dashboard 独立进程）→ core/dashboard/routes/spec_routes.py:252 _api_spec_error_clear；dashboard 进程的 state_machine 留痕不进 fenixd.log（dashboard.log 已停滞）。

## 方案

### A. lint 一次全报（core/deliverables.py）

改 lint_tasks_text 分组违规分支（:3329）的消息构造：分组不可解析时消息并列披露 item_count 与后续编号提示，形如「tasks.md 存在但未解析出任务分组——分组标题必须为 `## <编号>. <标题>` 形态；另有 N 条 checkbox 任务行，分组修正后还需为任务行补『组号.序号』编号」。N 取 _tasks_parse_counts 的 item_count；返回结构仍是字符串列表（调用方已聚合）。

### B. tasks.md 变化即时唤醒（core/event_bus.py）

1. 候选集预过滤：维护「status=drafted 且 STATE error 含 "tasks.md 可解析性 lint 未通过" 段（子串匹配）」的 spec 名单（随 _dispatch_changes/full scan 刷新），仅对该名单的 tasks.md 计算 checksum（新增监视面，不碰既有 STATE.md checksum 逻辑）。匹配用子串而非前缀：STATE error 是三类 lint 消息按固定顺序 `";".join` 的拼接串（promotion.py:160-170，Deliverables 段恒居首、tasks 段第二），「Deliverables+tasks」双违规 spec 的 error 以 Deliverables 段开头，前缀匹配会漏纳恰属人工起草高发形态的组合；该短语经全库 grep 核实唯一生成点为 promotion.py:165，子串匹配不误纳其他 drafted 错误。
2. 变化处理：名单内 spec 的 tasks.md checksum 变化 → 复用 handle_event("spec_drafted", name, entry)（同 _recover_one:413，自动继承 start_after 门与 promote_mode 短路）。
3. 同值抑制：触发重评后若 lint 仍败，STATE error 重写为同值——按 error 值+tasks.md checksum 联合去重，同值不重复触发、不重复打日志；变化（内容确实改了）才再评。
4. 防抖：checksum 计算本身幂等，2 秒轮询粒度下无须额外定时器。

### C. 清错留痕（core/dashboard/data/admin_actions.py）

clear_spec_error（:1529）清空成功时显式向共享 sink 写一行留痕（spec 名、清空来源=dashboard、时刻），弥补跨进程日志缺口；不改 STATE 写语义。

## 边界与护栏

- 触发条件用 error 子串（分段）匹配——「tasks.md 可解析性 lint 未通过」短语唯一生成点在 promotion.py:165，无第二写入方，子串匹配不误纳其他 drafted 错误。
- tasks.md 监视面单条异常隔离：名单内任一 spec 的 tasks.md 读取/checksum 异常只记 WARNING 并跳过该条，不汇入 _watch_loop 既有 fail_backoff 通道（event_bus.py:1098-1103）——否则单个 tasks.md 不可读会把全局 STATE.md watch 拖进 2→60s 退避、全量状态事件延迟；唤醒派发同样单条捕获记 WARNING（对齐 →testing 即时派发先例 :1373-1381，失败由 full scan 兜底重试）。
- 名单预过滤保证 2 秒轮询只对至多个位数 spec 做 tasks.md 读。
- promote_mode=manual 短路在出口处天然生效，无需新判断。
- 与在途 add-spec-title-promotion-gate 的碰撞面：两者都触 promotion.py 附近，落地顺序先到先得、任务面互不重叠（本 SPEC 不动 title 门）。

## 测试策略

- lint 全报：参照 tests/test_deliverable_lint.py 既有用例形态（test_violation_blocks_promotion_with_error :186、test_clean_declaration_promotes :200）补「分组缺失+多条未编号行」用例；保持 tests/test_task_artifact_ownership.py 5.4 零误拦守卫绿。
- 即时唤醒：参照 tests/test_startup_full_scan_async.py 的 event_bus+pm_engine 替身装配；四类用例（修复落盘秒级重评/仍败同值抑制/manual 不唤醒/非 lint error 不受影响）。
- 清错留痕：断言留痕行含 spec 名与来源。
