# 设计：drift 判定 pid 存活门控

## 现状坐标

- 判定：fenixd.py 启动自检（现 6542-6567 行）：daemon_ts - runtime_ts 大于 SUPERVISOR_RUNTIME_DRIFT_SECONDS（=24h，:126）即成条；severity=warning（:6623）、kind=escalation（:6620）、60 分钟去重（SUPERVISOR_LOG_DEDUP_MINUTES :182，窗口查询 :6584）、写入即 mark_handled（:6643-6644）。
- runtime 文件：bin/fenixd_supervisor.py:510-532 在 supervisor 启动时一次写入五键（sigkill_wait、started_at、pid、project_root、script_hash），pid/project_root 自 2026-09-18 起存在。
- 既有探活原语：core/fenix_session.py:259-275 supervisor_running()（/proc 扫描），目前只喂 supervisor_missing 信号，不参与 drift 判定。
- 设计注释 fenixd.py:120-125 把「漂移必然超限」假设为「文件残留自旧进程」的检出信号，与本机「supervisor 长寿数天、daemon 分钟级重启」常态相悖。

## 方案

1. 在漂移判定成条前插入 pid 门控，判定矩阵见 specs/supervisor-hosting/spec.md；存活检查用 os.kill(pid, 0)（ESRCH=死亡，EPERM=存活），身份校验读取 /proc 下该 pid 的 cmdline，匹配 b"fenixd_supervisor" 或 project_root 的字节串；cmdline 读取异常按「不可读」分支处理。改动收敛在 fenixd.py 单文件内，不新增模块。
2. 文案分叉：存活分支 evidence 改为「supervisor runtime 上报于 <上报时刻>，早于本次 daemon 启动 86400s 以上——pid <进程号> 存活，属长寿 supervisor 伴生（daemon 多代重启所致），无需处置」；死亡分支保留现文案。存活分支移除「建议重启」指引。
3. severity：存活分支 info，其余分支不变；去重、PROJECT_LOG 留痕、mark_handled 逻辑一律不动。
4. 同步修正 :120-125 的设计假设注释，写明长寿伴生为常态与 pid 门控语义。
5. 兼容性：runtime 文件缺 pid（2026-09-18 之前的旧格式）走原路径，不做数据迁移；旧文件随 supervisor 重启自然更新。

## 测试策略

- tests/test_daemon_lifecycle_races.py 扩展：存活 pid 用 os.getpid()（断言 info 且文案无「残留」「建议重启」）；死亡 pid 用已退出并回收的子进程 pid（断言 warning 且残留叙事保留）；pid 复用形态（伪造 cmdline 不匹配）按残留处理；缺 pid 字段回归现行为。
- 回归：test_stale_started_at_drift_warns 与 tests/test_supervisor_drift_log_dedup.py 全绿。