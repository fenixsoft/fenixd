## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx
  kind: new
- path: tests/test_stale_code_selfheal.py
  kind: new
- path: docs/help/07-safeguards.md
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: .fenix/config.yaml
  kind: reference
- path: .fenix/hooks/restart-daemon-when-idle.py
  kind: reference
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 陈旧检测的持续状态与可见性

- [x] 1.1 `fenixd.py`：把陈旧判定从「一次性置位」改为每检测周期重算的**持续状态** `self._code_stale`——在既有 30s 配置热更新检测点内调用既有纯函数 `code_files_changed_since(self._code_baseline_ns, self._code_files)` 求值并赋值，MUST NOT 保留「命中后永久跳过检测」的短路。既有 WARNING 文案保留。
- [x] 1.2 `fenixd.py`：移除模块级旗标 `_CODE_STALE_WARNED` 的一次性语义（改为按状态边沿记录：状态由假转真时落一次 WARNING，持续为真期间不重复刷日志），并在状态为真时经 AdminStore 写入一条 `signal_type: stale_code` 的 escalation 告警，描述须含「daemon 进程持旧代码，自愈将在连续空闲后触发重启」；同类型未处置告警 MUST 去重（复用既有 escalation 去重范式）。
- [x] 1.3 `fenixd.py`：状态由真转假时（重启后新进程 baseline 刷新，或磁盘代码回退）MUST NOT 新增陈旧告警，且须在日志中记录状态解除。
- [x] 1.4 `tests/test_stale_code_selfheal.py`：覆盖陈旧命中写告警、多周期持续为真不重复写未处置告警、状态转假不再产生新告警、以及「持续为真期间日志不重复刷 WARNING」四项。

## 2. 空闲判定与自愈触发

- [x] 2.1 `fenixd.py`：新增空闲判定——同时满足 `self.pm_engine._active_runs == 0` 且 admin 处置 worker 池无在途任务。admin 池在途判定须基于该池自身的计数或队列状态（如为池维护在途计数器），MUST NOT 依赖 `ps` 或外部进程扫描；`_admin_executor` 为 `None`（未启用后台池）时该维度视为空闲。判定逻辑须独立成可单测的函数或方法，便于隔离测试。
- [x] 2.2 `fenixd.py`：主循环新增自愈触发——当 `self._code_stale` 为真、`stale_code_selfheal.enabled` 为真、且 `core.fenix_session.supervisor_running(PROJECT_ROOT)` 为真时，累计连续空闲时长；达到 `idle_confirm_seconds` 后 `touch` `.fenix/restart_request` 并记录日志（含触发原因与等待时长）。任一非空闲信号出现时 MUST 立即清零计时。
- [x] 2.3 `fenixd.py`：边界条件——`.fenix/restart_request` 已存在时 MUST NOT 重复写入，也不重复记录触发日志；`supervisor_running` 为假时 MUST NOT 写入（并须在日志中明示「未受托管，自愈跳过」）；配置关闭时 MUST NOT 写入，但须在日志中明示「自愈已被配置关闭」。
- [x] 2.4 `tests/test_stale_code_selfheal.py`：覆盖连续空闲达标触发（写入 restart_request）、活跃 run 出现时计时清零、admin 在途时判非空闲、`restart_request` 已存在不重复写、`unmanaged` 不触发、配置关闭不触发六项。

## 3. 配置与界面

- [x] 3.1 `core/config.py`：新增 `stale_code_selfheal` 节的读取，暴露 `enabled`（布尔，缺省 `true`）与 `idle_confirm_seconds`（整数秒，缺省 `120`）；节缺失、键缺失或值非法（非布尔 / 非正整数）时 MUST 回退缺省值且不抛异常、不使 daemon 启动失败。读取须走既有配置对象，使 30s 热更新自然生效。
- [x] 3.2 `core/dashboard/server.py`：`_api_config_get` 的返回体与 `_api_config_post` 的写入体扩展 `stale_code_selfheal` 节（`enabled` / `idle_confirm_seconds`），保持既有原子写与校验失败返回 400 的语义；非法值 MUST 返回可读错误而非静默接受。
- [x] 3.3 `core/dashboard/static/src/services/dashboard.ts`：配置读写类型与调用扩展 `stale_code_selfheal` 节字段。
- [x] 3.4 `core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx`（新建）：展示并可编辑 `enabled`（开关）与 `idle_confirm_seconds`（数字输入），含简短的语义说明（陈旧时空闲多久自动重启）；保存走既有配置写回路径并给出成功/失败反馈。`core/dashboard/static/src/pages/settings/index.tsx` 挂载该面板，与既有各 Panel 的排版一致。
- [x] 3.5 `tests/test_stale_code_selfheal.py`：覆盖缺省值生效、非法值回退不中断、`enabled: false` 时不自愈、以及 `/api/config` 读写该节往返一致。

## 4. supervisor 启动失败熔断

- [x] 4.1 `bin/fenixd_supervisor.py`：记录每次 daemon 启动的时刻，在其退出时计算存活时长；存活 **< 60 秒**计为一次启动失败，累计连续失败次数；存活 **≥ 60 秒**时 MUST 重置连续失败计数为 0。阈值以具名常量表达，不得与既有 `DEFAULT_SIGKILL_WAIT_SECONDS` / `DRAIN_MARGIN_SECONDS` 共用（语义相反）。
- [x] 4.2 `bin/fenixd_supervisor.py`：连续失败达 **3 次**时停止自动拉起，写入熔断标记文件（`.fenix/supervisor_fused`，内容含时间戳与失败次数），并在 `.fenix/logs/supervisor.log` 落 critical 记录；主循环此后 MUST NOT 再拉起 daemon，直到熔断标记被清除（或 supervisor 进程重启——计数与标记的判定须使新 supervisor 进程不继承旧熔断）。
- [x] 4.3 `bin/fenixd_supervisor.py`：熔断触发时经既有告警通道产出 critical 告警，描述须含「daemon 连续启动失败，已停止自动拉起」与人工处置指引（修复代码 → 清除熔断标记 → 重启 supervisor）。
- [x] 4.4 `tests/test_stale_code_selfheal.py`：覆盖连续 3 次短命退出触发熔断且不再拉起、存活超 60 秒重置计数、清除标记后恢复拉起、以及熔断状态不被新 supervisor 进程继承四项。对 `time.sleep` / 子进程退出做可注入替身，避免测试真实等待。

## 5. 移除冗余的 when-idle 脚本

- [x] 5.1 `.fenix/config.yaml`：删除 `hooks.specs.add-judge-artifact-gate` 下 `id: h-judgegate-restart` 的 `restart-daemon-when-idle` hook 项；若删除后该 SPEC 的 hook 列表为空，一并清理其空键，保持 YAML 结构合法。
- [x] 5.2 `.fenix/hooks/restart-daemon-when-idle.py`：删除该脚本文件；`.fenix/hooks/__pycache__/` 中其编译产物顺手清理（若存在）。
- [x] 5.3 落地前确认该 hook 未被其他 SPEC 或配置引用（全量 grep `restart-daemon-when-idle`），确认无引用后执行删除。

## 6. 文档

- [x] 6.1 `docs/help/09-config.md`：新增 `stale_code_selfheal` 节说明（两个键、缺省值、热更新语义、关闭后陈旧告警仍产生）。
- [x] 6.2 `docs/help/07-safeguards.md`：补「代码陈旧自愈与启动失败熔断」小节——陈旧状态如何可见、空闲判定口径（无 agent run 且无 admin 在途）、未托管不自愈的原因、熔断阈值与人工恢复步骤。
- [x] 6.3 `docs/help/08-dashboard.md`：设置页新增 `stale_code_selfheal` 面板的说明。

## 7. 回归验证

- [x] 7.1 运行 `python3 -m pytest tests/ -q` 全量通过，且 `tests/test_stale_code_selfheal.py` 全绿。
- [x] 7.2 在 `core/dashboard/static` 执行 `npm install --no-audit --no-fund` 与 `npm run build` 成功，设置页可正常加载并读写 `stale_code_selfheal` 面板（构建产物 `core/dashboard/static/dist/` 为 gitignored 运行时产物，不入库）。
- [x] 7.3 确认移除 when-idle hook 后 `hooks.specs.add-judge-artifact-gate` 配置仍可被既有 hook 引擎正常加载（YAML 合法、无悬挂引用），既有 hook 相关测试全绿。
