## Context

add-impl-ocr-parallel-lane 把实现分支收尾代码审查摘成框架侧并行车道：daemon 内线程（`impl-ocr-lane-<spec>`）在 detached worktree 跑 `bin/ocr_review.py review`，run 形态走 `impl-ocr-<spec>-<ts>.jsonl` 最小生命周期（`_write_impl_ocr_run_events` 只在启动与终态各写一批事件，设计即「时间线可见，不经 _run_claude」）。orphaned_state 无驱动探针 `spec_is_undriven`（admin_monitor.py:584，与 event_bus 恢复共用口径）四条件 AND：

1. 条件① `_has_recent_spec_run`：run 转录 mtime 超 `ORPHANED_RUN_GRACE_SECONDS`（120s）→ 车道只写 start/终态，运行中 mtime 停滞 → **误真**；
2. 条件② `_pgrep_live_worktree`：pgrep 模式 `impl-<spec>-` 只能命中 cmdline 含 spec 名的 claude 进程，ocr 子进程 argv 无 spec 名 → **误真**；
3. 条件③ 无 `_cancelled_hold`/`start_after`/退避 → 真；
4. 条件④ 无排队派发条目 → 真。

叠加 15 分钟阈值即系统性误报（实证 2026-09-22 add-code-fix-manual-trigger：11:58 车道启动审 63 文件 +6694 行，12:13 误报成条，admin run 空转一轮）。

关键现场约束：STATE 的 `_ocr_join_wait` **没有 boot 恢复**——daemon 在停等中重启后，spec 的自愈恰恰依赖「orphaned_state → admin 处置 → testing→verifier 重验入队」直通道。任何「把 `_ocr_join_wait` 当有意等待豁免」的方案都会遮蔽重启后的真孤儿。

## Goals

- 车道在跑期间（无论 diff 多大、审查多久）不再产生 orphaned_state 误报。
- daemon 重启后的真孤儿上报与既有自愈链**完全不遮蔽**。
- 探针判定函数 `spec_is_undriven` 与两个 run 终态分类器**行为零改动**（回归钉住即可）。

## Decisions

### D1 主案 = 车道运行中心跳（消费既有条件①，不新增豁免）

`run_impl_ocr` 在审查子进程运行期间起后台定时线程，按 ≤45s 间隔（< 120s 宽限，留出调度抖动余量）经既有 `_write_impl_ocr_run_events` 追加 `type: "progress"` 事件（含 `review_range` from/to 与 `elapsed_seconds`）。效果链：mtime 持续刷新 → 条件①持续为假 → AND 链整体为假 → 不误报。

备选否决记录：
- **补全条件②进程识别**（/proc 扫 cwd/worktree 名）：pgrep 看不到 env 与 cwd，需自写 /proc 遍历，脆弱且平台耦合；
- **`_ocr_join_wait` 有意等待豁免**：该字段无 boot 恢复，重启后真孤儿被永久遮蔽（见 Context），且豁免需要保质期机制反而更复杂；
- **admin_monitor 读内存登记表 `_ocr_lane_inflight`**：登记表是引擎实例内存态，admin_monitor 与引擎的依赖方向、以及重启后登记表清空但 STATE 停等残留的组合态都要另处理，引入跨模块耦合。

心跳方案的额外收益：时间轴/运行记录的 run 节点在车道运行期 mtime 活跃（duration 实时、dashboard `_RUN_META_CACHE` 按 mtime 失效自然重算），为后续「时间轴显示车道进度」留了数据源（另案）。

### D2 线程模型与停跳顺序

- 定时线程 `threading.Thread(daemon=True)` + `threading.Event` 停跳位；循环 `Event.wait(interval)` 保证可中断。
- 停跳顺序 MUST 是：子进程返回（含硬超时）→ `stop_event.set()` + `join(timeout=…)` → 写终态事件 → 清 worktree。保证「终态事件末行后置」不变量与无写竞态（心跳线程死亡后主线程独占写）。
- 心跳写失败静默（观测通道，`_write_impl_ocr_run_events` 既有语义），MUST NOT 影响车道收尾；车道整体 MUST NOT 抛未捕获异常的既有约束不变。

### D3 事件类型命名 `progress` 与分类器兼容

`progress` 不在 `_RUN_TERMINAL_STATUS_MAP`（runs.py:131）→ `classify_run` 走缺省 `"running"`；`AdminMonitor._run_terminal_status` 只认 `result`/`error` → 亦判 running。两侧**零改动**，但各加一条回归测试钉住：未来任何人往终态映射表加类型时不会悄悄把心跳当终态。渲染层对未知事件类型的容忍已按既有代码核实（评审留痕）：车道 run 事件级渲染链为 RunRecordModal → ClaudeOutputPane → `runEvents.ts` 分类表，`progress` 不在分类表与 `SILENT_KINDS`、且无顶层字符串 content → 落入 fallback 静默路径，不产出可见行、不报错。本 SPEC 不涉前端改动，tasks 清单亦不新增前端验证场景（2.2 仅钉后端两分类器），本句仅为设计依据留痕。

### D4 显式不作为

- 不改 `spec_is_undriven`、`_pgrep_live_worktree`、`_has_recent_spec_run`；
- 不加配置键（间隔常量入模块，硬编码 45s，与车道级超时 2400s 无交互）；
- 不动 `_ocr_join_wait` 语义与 join 门禁；
- 不做时间轴进度展示（前端消费属 add-timeline-ocr-lane-visibility 另案）。

## Risks

- **心跳线程泄漏**：任何路径漏 set 停跳位 → 线程随 daemon 进程存活常驻写文件。缓解：try/finally 全覆盖 + join 上限 + daemon=True 兜底；测试覆盖异常收尾路径。
- **终态事件与心跳竞态**：停跳 join 未完成即写终态 → 末行可能不是终态，破坏「终态后置」分类不变量。缓解：D2 顺序 + join 同步；回归测试断言终态末行。
- **归档竞态**：run 完成后文件被 archive 清理迁移，心跳若未停会写到旧路径复活文件。缓解：D2 停跳先于一切收尾（终态写、归档、worktree 清理）。
- **事件类型撞车**：未来框架给 run 流引入同名 `progress` 语义（如实现者转录），语义漂移。缓解：spec 钉死本事件的字段集与「非终态」性质；两个分类器回归钉住。
