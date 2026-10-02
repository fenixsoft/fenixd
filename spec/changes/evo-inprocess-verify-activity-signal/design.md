# Design: inprocess-verify-activity-signal

## 背景与痛点

in-process 全量验证（daemon 线程 fenix-verifier-<spec> + asyncio.run，无 run 文件/子进程）对 spec_is_undriven 四条件全部不可见；孤儿探测（admin_monitor.py:2666）、recovery（event_bus.py:439）与处置复位直通道（admin_monitor.py:4679，不经判定函数）三出口在验证活跃期误判重派，2026-10-02 实付 $1.289 调查 run + 三批 23 场景交错。

## 目标

- 判定读侧补两类活性信号：零调参的线程探测（主）+ 进度文件独立窗口 mtime（辅）。
- 三个出口全部豁免在飞验证；验证结束后判定口径与现状逐字节一致。

## 非目标

- 不改 verify_engine 写侧、不以 _active_runs 计数为判据、不动阈值/告警级别、不动 legacy 外置 verifier 车道。

## 方案

1. core/admin_monitor.py：新增模块级 helper（如 `inprocess_verify_active(project_root, spec_name, *, window_seconds=None) -> bool`）：(a) threading.enumerate() 存在 name == f"fenix-verifier-{spec_name}" 的活线程 → True；(b) .fenix/verify-progress/<spec>.json mtime 落入独立窗口（新常量，缺省 900s=对齐 DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES:178，与 ORPHANED_RUN_GRACE_SECONDS:175=120s 显式区隔）→ True。文件缺失/超窗/线程不在 → False。
2. spec_is_undriven（:706-778）条件序列末尾并入 helper；docstring（:714-748）按既有格式增补条件⑤由来与本次实证（告警 id 120b47256071/e79234cabae3、三批交错时间线）。
3. _reset_orphaned_after_disposition（:4679）testing 分支重派前调 helper，True → 顺延（保留原复位语义，仅延后重派；顺延不新增状态、下一轮处置扫描自然重试或线程退出后放行）。
4. event_bus._recover_testing（:439）无需改代码——它已调用 spec_is_undriven，条件⑤自动生效；仅当实现中发现调用形态差异时才同步。

### 关键约束

- 线程名是隐式契约：helper MUST 从 queue.py 的线程命名单点取值或抽公共常量/函数，MUST NOT 在两处硬编码字面量。
- 独立窗口 MUST NOT 复用 120s 宽限：进度文件按逐场景节奏写（fix-verify-progress-granularity），但单场景可跑 4-5 分钟（实测批间隔），120s 会把「正在长跑」误判为停滞。
- 假阳性防线：进度文件是起跑即写（engine.py:324），run 崩溃残留的新鲜 mtime 可能短暂豁免孤儿判定——以线程探测为主判据、mtime 仅作辅证（AND 语义不可用——线程探测在跨进程场景不可得；OR 语义下残留风险可接受：下一窗口 mtime 超窗即恢复）。
- 测试装置：线程用 threading.Thread(name=f"fenix-verifier-{spec}", daemon=True) 造活/退出两态；进度文件用 tmp_path 造 mtime 新旧两态（os.utime）。

## 测试策略

- 扩展 tests/test_orphaned_state_signal.py：条件⑤线程两态、进度 mtime 两态与窗口边界、120s 不足而独立窗口豁免的对照、处置直通道顺延与放行。
- 回归：tests/test_pm_recovery.py、tests/test_inconclusive_loop_escalation.py、tests/test_impl_ocr_parallel_lane.py（OCR 心跳先例路径不受扰）。