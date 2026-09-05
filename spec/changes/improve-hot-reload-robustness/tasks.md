## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_config.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
```

## 1. 未知键逐键降级（core/config.py）

- [ ] 1.1 `_validate_agent_models`（config.py:388-393）：未知 agent 类型键由 `raise ValueError` 改为逐键 ERROR 告警（文案含未知键名、本进程已知类型列表、`touch .fenix/restart_request` 处方）+ `continue`；键保留在有效配置中不剔除
- [ ] 1.2 同一未知键每进程生命周期只报一次（模块级已告警键集合，仿 `_DEPRECATED_STUCK_WARNED` 旗标模式），30s 重试重报期间静默跳过
- [ ] 1.3 `agents.models` 整段非 dict：由 raise 改为忽略该段 + ERROR 告警（对齐 `_load_optional_yaml` 哲学），其余段照常校验应用
- [ ] 1.4 删除 `config.py:134` 死代码二次 `_validate` 调用（`resolve_config` 内部已校验同一份 fresh）
- [ ] 1.5 分类线锁定：已知键的值类错误（provider 链非法等）与其他段结构性 raise 一律不动，仅"键集不匹配"降级

## 2. 代码陈旧检测（fenixd.py）

- [ ] 2.1 `initialize()` 记录代码 mtime 指纹 baseline：glob `fenixd.py + core/**/*.py` 缓存文件列表，取 max `st_mtime_ns`
- [ ] 2.2 检测逻辑提取为可测纯函数（如 `code_files_changed_since(baseline, roots)`：任一文件 mtime > baseline 即 True，文件缺失忽略）
- [ ] 2.3 `_maybe_reload_config` 挂检测：磁盘代码 mtime 超 baseline → 打印一条"磁盘代码较进程启动时已更新，建议重启"WARNING，每进程生命周期一次（模块级旗标去重）

## 3. daemon_errors 升级口径重写（core/admin_monitor.py）

- [ ] 3.1 常量调整：`DAEMON_ERROR_THRESHOLD = 2`（语义改为"窗口内同指纹最少复现次数"），新增 `DAEMON_ERROR_WINDOW_MINUTES = 10`、`DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES = 5`，均保持模块常量不进 config
- [ ] 3.2 新增 `_error_fingerprint(component, message)`：`sha1(component + "\x00" + normalize(message))`；归一化保守集——ISO-8601 时间戳→`@`、UUID→`~`、≥16 位 hex→`~`、纯数字序列→`#`，不动路径与文字骨架
- [ ] 3.3 重写 `_detect_daemon_errors`（admin_monitor.py:510-533）：逐行 JSON 解析（logger 保证单行 JSON），非 JSON 行回退 raw 行归一化 hash 不崩；统计 10 分钟窗口内同指纹复现次数 + 最近两次间隔 ≤5 分钟约束；timestamp 缺失/解析失败行 fail-closed（仍计入桶、间隔按满足）；废弃"尾部物理连续段"口径
- [ ] 3.4 signal 的 description/evidence 文案适配新口径（如"错误 X 于 10 分钟窗口内复现 N 次"，不再写"连续 N 条 ERROR"）
- [ ] 3.5 顺带优化：日志读取由全量 `read_text` 改为 seek 尾部回退读 256KB，避免日志增长后每轮全量读

## 4. 测试（tests/test_config.py、tests/test_admin.py）

- [ ] 4.1 test_config.py：未知键容忍不抛且告警含处方/implementer 分配完整保留；未知键 + 已知键值类错误共存 → 仍整段拒绝；未知键后跟合法已知键 → 已知键生效；models 段非 dict → 忽略该段其余照常；启动路径容忍未知键不 FATAL；值类非法原子保留回归锁（resolve_config_into 失败后原 config 逐键不变）；`get_agent_model_assignment` 无白名单拦截
- [ ] 4.2 陈旧检测单测：无变更 False/core 文件更新 True/fenixd.py 更新也算/文件缺失忽略
- [ ] 4.3 test_admin.py：事故回归（两条同 message ERROR 相隔 30s 中间夹 INFO → 触发）；单条不触发；两条不同错误各 1 次不触发；同指纹相隔 8 分钟不触发；第 1 次 11 分钟前不触发；message 内嵌变量不同归一化后触发；非 JSON 行不崩且回退正确；缺 timestamp 重复 ERROR 触发（fail-closed）；触发后 cooldown 内不重复唤起

## 5. 验证

- [ ] 5.1 全量单测通过（现有 test_daemon_errors 用例在新口径下兼容通过）
- [ ] 5.2 模拟事故场景：旧白名单进程语义 + 含新键配置 → 热重载成功、单次降级告警、无 30s 告警刷屏、陈旧检测 WARNING 出现
- [ ] 5.3 验证升级时序：同指纹 ERROR 每 30s 两条 → 下轮巡检即产生 critical signal（模拟巡检周期，不再依赖日志安静度）
