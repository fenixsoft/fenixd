# Design: supervision-timeout-config-consistency

## 背景与痛点

配置漂移：`agents.run_timeout_seconds=15000`（.fenix/config.yaml:22）vs `agents.timeout_supervision.absolute_max_seconds=14400`（:27），监督运行时兜底 18600s 生效，同一个 run 被抬升后的 18600s 封顶终止（.fenix/logs/fenixd.log:15054）；5 条同文案 ERROR 复现两日（13181/13218/14985/15018/15051）。

两处口径各自手写（实测）：

- `core/config.py:1241` `effective_supervision_absolute_max_seconds`：硬编码 `SUPERVISION_EXTENSION_SECONDS = 7200`（config.py:29）⇒ 下限 22200s；只告警、不阻断、不对齐。该 guard 唯一消费点是 runner.py:2583（仅与 run 超时比较后打 DEBUG），不参与实际封顶值。
- `core/agent_runner/liveness.py:777-789`：`floor_absolute_max = run_timeout + max_extensions × extension_seconds` ⇒ 基础档 18600s（fast-track higher 档 `max_extensions += 2` ⇒ 22200s）；此处才是实际封顶值来源，5 条 ERROR 即由此产生。

## 目标

- 单一派生口径：两处调用同一函数，禁止各自手写常数（消除 22200/18600 双份表述）。
- 启动/热更新不一致即显式处理（默认自动对齐并持久化；关闭对齐则阻断），消除同文案 ERROR 复发。
- 操作者配置意图可见：不一致时 ERROR 同时给出「抬升 absolute_max」与「下调 run_timeout」两条修正路径。

## 非目标

- 不动监督运行时决策矩阵，不改各档位现行下限数值（18600s / 22200s）。
- 不强制改 run_timeout 值。

## 方案

1. `core/config.py` 新增单一派生函数，例如：

   `ConfigLoader.supervision_floor(config, agent_type=None, extension_budget=None) -> Optional[float]`

   - `生效超时 = ConfigLoader.effective_run_timeout_seconds(config, agent_type)`（含 `agents.timeout_overrides.<agent_type>` 覆盖，缺省回退全局/9000）；
   - `续期预算 = extension_budget if 显式传入 else max(0, max_extensions)`（fast-track + `_fast_track_scale_tier == "higher"` 时调用方传 `max_extensions + 2`，保持既有加成语义）；
   - 返回 `生效超时 + 续期预算 × extension_seconds`；`enabled=false` 或缺段返回 `None`（不校验）。
   - `effective_supervision_absolute_max_seconds` 改为消费该函数（删除 `SUPERVISION_EXTENSION_SECONDS = 7200` 手写常数，改为「最大续期预算」派生量），并新增 fail-fast 分支（见 5）。
2. `core/agent_runner/liveness.py:777-789` 改为调用同一函数（传入该 agent 的实际预算，含 fast-track 档位加成），删除手写 `floor_absolute_max` 表达式；**数值行为不变**。
3. **配置校验层口径 MUST 取全部署最大可达下限**：`max(全局 run_timeout_seconds, 全部 timeout_overrides 值) + (max_extensions + 2) × extension_seconds` = 当前 15000 + 4×1800 = 22200s。理由（实测）：仅按基础预算 2×1800 得 18600s 时，fast-track higher 档运行时仍需 22200s（liveness.py:779-792），该档会再次命中同文案 ERROR，「消除复发」目标落空；且 7200（= 4×1800）与模板 16200（= 9000 + 4×1800）已确立「按最大续期预算」的既有口径，本改动只把常数改为派生，MUST NOT 下调保守性。
4. 校验点：`ConfigLoader._validate`（config.py:296，启动经 `resolve_config`（fenixd.py:213）与热更新经 `resolve_config_into`（fenixd.py:645）两条路径共入）执行一致性校验。
5. 不一致处置（**顺序约定，避免两条要求互斥**）：
   - 默认（`timeout_supervision.auto_align` 缺省 true）：ERROR 留痕（含两侧值、配置层下限、两条修正建议）→ 抬升 absolute_max 至下限 → 内存生效并持久化；该分支 MUST NOT 抛异常，保证启动与热更新均可继续。
   - 显式关闭自动对齐：MUST fail-fast —— 启动/加载即失败；热更新经既有 `try/except`（fenixd.py:512-515）+ `resolve_config_into`（失败不触碰旧 dict，config.py:252-264）语义自然满足「拒绝新配置、回滚旧值」，无需新机制。注意：此档位下任意一处不一致会让**整份**热更新失败（旧配置继续运行、其它键改动也不生效）——这正是把自动对齐设为缺省开启的原因。
   - 持久化 MUST 复用既有配置写路径 `core.dashboard.data.write_config`（`core/dashboard/data/config_admin.py`：受管键白名单 + 原子写 + 配置头注释），由 daemon（fenixd.py:213 启动、fenixd.py:645 热更新）在完成校验后调用；`core/config.py` MUST NOT 直接写配置文件（避免与 launcher/dashboard 写路径竞争、避免 safe_dump 丢注释）。对齐值需可写入 ⇒ `_AGENTS_MANAGED_SUBKEYS`（config_admin.py:24-33）须补 `timeout_supervision` 受管子键。
6. `.fenix/config.template.yaml` 补齐注释与对齐示例值（`absolute_max_seconds MUST ≥ max(生效超时) + (max_extensions + 2) × extension_seconds`；示例 9000 + 4×1800 = 16200，即现有 108/258 行取值）。

## 测试策略

- 新文件 tests/test_supervision_timeout_consistency.py：单一派生函数数值（运行时基础档 15000+2×1800=18600、fast-track higher 档 22200；配置层最大下限 15000+4×1800=22200）、两处共用同一实现（断言相等/同一函数对象）、不一致启动行为（自动对齐开启 → 对齐+持久化+无阻断；关闭 → fail-fast）、热更新拒绝回滚、对齐持久化经写路径落盘五类。
- 既有 tests/test_config.py、test_system_settings_config.py、test_liveness_hang_discrimination.py、test_run_lifecycle_hardening.py（`TestAbsoluteMaxCap`：`started_ago=14000`/cap_floor 12600 等断言依赖运行时基础档预算）、test_run_lifecycle_governance.py（governance 封顶用例）回归——运行时数值 MUST 保持不变。
