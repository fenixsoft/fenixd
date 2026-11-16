# 设计：drift 判定 pid 存活门控

## 现状坐标

- 判定：fenixd.py 启动自检 `_check_supervisor_drain_consistency`（现约 6536-6605 行，漂移比较在 6580-6605；评审时实测坐标）：daemon_ts - runtime_ts 大于 SUPERVISOR_RUNTIME_DRIFT_SECONDS（=24h，:126）即成条；severity=warning（:6661）、kind=escalation（:6658）、60 分钟去重（SUPERVISOR_LOG_DEDUP_MINUTES :182，窗口查询 :6621-6623）、写入即 mark_handled（:6681-6682，`severity_needs_human` 仅认 critical/major，core/admin_store.py:100）。同一自检轮次本族 warnings 至多一条（缺文件/解析失败/顶层非对象/sigkill_wait/漂移各分支互斥，漂移段前有 `if not warnings` 短路），成条 severity 单值、无混合批。注意：项目 `shutdown_drain_seconds: 0` 时整段自检在 :6537 短路（含漂移判定），告警族仅在 drain>0 运行形态下活跃。
- runtime 文件：bin/fenixd_supervisor.py `_write_supervisor_runtime`（现 515-537 行）在 supervisor 启动时一次写入五键（sigkill_wait、started_at、pid、project_root、script_hash），pid/project_root 自 2026-09-18 起存在。
- 既有探活原语：core/fenix_session.py:259-275 supervisor_running()（/proc 扫描），目前只喂 supervisor_missing 信号，不参与 drift 判定。
- 设计注释 fenixd.py:120-125 把「漂移必然超限」假设为「文件残留自旧进程」的检出信号，与本机「supervisor 长寿数天、daemon 分钟级重启」常态相悖。

## 方案

1. 在漂移判定成条前插入 pid 门控，判定矩阵见 specs/supervisor-hosting/spec.md；存活检查用 os.kill(pid, 0)（ESRCH=死亡，EPERM=存活），身份校验读取 /proc 下该 pid 的 cmdline，匹配 b"fenixd_supervisor" 或 project_root 的字节串。cmdline 读取异常分两类：FileNotFoundError/ProcessLookupError（探活与读取之间的竞态窗口内进程刚退出）按「死亡」分支走残留 warning；其余异常（权限/容器不可读）按「不可读」分支走存活 info。pid 解析为非正整数（≤0 或非 int）按「不可解析」走旧行为——os.kill(0/-N, 0) 探测的是调用方进程组而非目标进程，语义失真。已实测本机活体 supervisor cmdline（`python3 …/.fenix/bin/fenixd_supervisor.py --project-root …`）同时含 fenixd_supervisor 与 project_root 两个 token，匹配可行。改动收敛在 fenixd.py 单文件内，不新增模块。
2. 文案分叉：存活分支 evidence 改为「supervisor runtime 上报于 <上报时刻>，早于本次 daemon 启动 86400s 以上——pid <进程号> 存活，属长寿 supervisor 伴生（daemon 多代重启所致），无需处置」；死亡分支保留现文案。存活分支移除「建议重启」指引。文案分叉以整条成记录口径为准（description/evidence/recommended_action 合并）：现去重标记记录的 `recommended_action` 为全分支共享硬编码「重启 supervisor 使排水窗口与上报刷新生效」（:6669），存活分支下该字段 MUST 同步改为「无需处置」类文案，不得保留「重启 supervisor」指引。
3. severity：存活分支 info，其余分支不变；去重、PROJECT_LOG 留痕、mark_handled 逻辑一律不动。
4. 同步修正 :120-125 的设计假设注释，写明长寿伴生为常态与 pid 门控语义。
5. 兼容性：runtime 文件缺 pid（2026-09-18 之前的旧格式）走原路径，不做数据迁移；旧文件随 supervisor 重启自然更新。

## 测试策略

- tests/test_daemon_lifecycle_races.py 扩展：存活 pid 用例 MUST 控制 cmdline 匹配内容——裸 os.getpid() 在 pytest 进程下 cmdline（pytest argv）既不含 fenixd_supervisor 也不含临时 project_root，按判定矩阵会落入「pid 复用」分支判残留 warning，info 断言自败；须 spawn 带 fenixd_supervisor token argv 的子进程（如 `[sys.executable, "-c", "import time;time.sleep(30)", "fenixd_supervisor"]`，测毕 terminate 回收）或等效 monkeypatch。死亡 pid 用已退出并回收的子进程 pid（断言 warning 且残留叙事保留）；pid 复用形态（伪造 cmdline 不匹配）按残留处理；缺 pid 字段回归现行为。既有用例装置 `_write_runtime`（tests:1069-1073）只写 sigkill_wait/started_at 无 pid，天然走「缺 pid 旧行为」分支，test_stale_started_at_drift_warns 等既有用例无需改动即回归绿。
- 回归：test_stale_started_at_drift_warns 与 tests/test_supervisor_drift_log_dedup.py 全绿。