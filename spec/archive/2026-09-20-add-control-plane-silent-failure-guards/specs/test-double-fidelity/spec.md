# 测试替身保真守卫（test-double-fidelity）

## 需求

### R1 替身签名保真
- 测试套件 SHALL 提供一项静态守卫，扫描 `tests/**/*.py` 中所有类定义的方法，对方法名与生产方法名匹配者比对 `(必填位置参数个数, 是否含 *args, 是否含 **kwargs)`。
- 替身若比生产方法**更宽容**——含 `*args` 或 `**kwargs`——MUST 判违规。
- 替身若**必填位置参数个数少于**生产方法 MUST 判违规。
- 替身必填更多不判违规（会在测试执行时当场 `TypeError`，无静默风险）。
- `self`/`cls` 剥离规则与 `callsite-arity-guard` 一致；`staticmethod` 不剥离首参。

#### Scenario: 宽容替身被拦截
- **WHEN** 生产 `PMEngine.handle_event(self, event_kind, spec_name, spec_entry)` 有 3 必填位参，而某测试类写作 `def handle_event(self, event_kind, spec_name, **kwargs)`
- **THEN** 守卫测试失败，报出 `文件:行 类.方法 fake=(req,vararg,kwarg) prod=(req,vararg,kwarg)`

#### Scenario: 忠实替身放行
- **WHEN** 替身写作 `def handle_event(self, event_kind, spec_name, spec_entry)`
- **THEN** 不判违规

#### Scenario: 必填更多放行
- **WHEN** 替身必填位置参数多于生产方法
- **THEN** 不判违规（无静默吸收风险）

### R2 候选 seam 构造规则
- 参与比对的生产方法名 MUST 满足：在 `core/` 中**唯一签名**、该签名不含 `*args`/`**kwargs`、非 dunder、且不在宽泛名黑名单（logger 风格 `info`/`warning`/`error`/`debug`/`critical`/`exception`/`log`/`_log`；容器风格 `get`/`items`/`keys`/`values`/`append`/`update`/`read`/`write` 等；时间工具 `now`/`isoformat` 等）内。
- 守卫 SHALL 提供显式白名单（最小粒度 `(文件, 类名, 方法名)`）豁免确有意为之的宽容替身。

#### Scenario: 宽泛名不参与
- **WHEN** 生产里有多个类各自定义 `warning(self, ...)` 或 `get(self, ...)`
- **THEN** 这些方法名不参与判定，避免跨类同名误报

### R3 现有偏离替身收紧
- 本改动落地时 SHALL 将以下既有偏离替身收紧为与生产签名一致的显式签名（消灭守卫的既有红灯，令守卫"零欠债"）：
  - `tests/test_run_budget_continuity.py`：`FakePM._send_human_escalation_alert`
  - `tests/test_liveness_hang_discrimination.py`：`FakePM._send_human_escalation_alert`
  - `tests/test_spec_review_agent.py`：`_FakeRunner._check_agent_result_artifact`、`_RecordingRunner._check_agent_result_artifact`（2 处）
  - `tests/test_self_evolution.py`：`_FakeEvolutionRunner._run_claude`

#### Scenario: 收紧后守卫零违规
- **WHEN** 上述替身全部改为显式签名后运行守卫
- **THEN** 无违规（白名单为空即可通过）

### R4 守卫有效性自检
- 守卫测试 SHALL 包含"有牙"自检：断言候选 seam 方法集规模高于下限。

#### Scenario: 候选集退化即失败
- **WHEN** 候选 seam 集退化为 0 或低于下限
- **THEN** 自检断言失败

## 验收标准
- 单元测试：把某替身临时改回 `**kwargs`，守卫必须失败（拔牙验证）；改回显式签名后必须通过。
- 落地实证：对当前 `tests/` 运行守卫，违规数 0。
- 收紧后的上述 4 个测试文件全部通过。
