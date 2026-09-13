# 验证报告：add-verify-unreachable-failfast

> ⚠️ 本报告由框架于 2026-09-12T03:31:35Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.70M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-probe-timeout-failfast | 就绪探针超时短路本轮（spec「就绪探针超时短路本轮」）：monkeypatch _ensure_app_reachable 返回 (False, False, "就绪探针超时（120s）...")，驱动真实 _run_three_stage_verification（core/pm_engine/verification.py:1792-1820 短路块）→ 断言 VerifyEngine 未创建/未运行（场景执行数=0）、STATE 落 blocked（error 含「验证环境阻塞（应用不可达）」与超时 note）、admin_invoke_request.json 落盘（自动呼叫 Administrator）、admin_alerts.json 含 verify_env_blocked 信号、不产 report.json / verification-report.md。 | pass | 0/10 | - |
| cli-prepare-failure-failfast | 契约 prepare 失败同样短路（spec「prepare 失败同样短路」）：monkeypatch _ensure_app_reachable 返回 (False, False, "验证契约 prepare 失败: npm ERR! exit 1")，驱动真实验证管线 → 与探针超时同款短路：0 场景、blocked、升级失败原因（error 含 prepare 失败文案）、绝不继续跑场景。 | pass | 0/8 | - |
| cli-contract-missing-no-dup-signal | 契约缺失子案只补落态不重写信号（spec「契约缺失子案只补落态不重写信号」）：构造临时项目（web 场景集 + 无 .fenix/verify.yaml），_ensure_app_reachable 走真实契约缺失分支（verification.py:845-884 内部唯一写入 verify_contract_missing 信号）返回 (False, False, note) → 短路仅调用 _escalate_env_blocked，断言告警 store 中该 spec 的 verify_contract_missing 信号仍为一条（count=1，短路不追加第二条）、blocked、admin 呼叫落盘、无 report。 | pass | 0/10 | - |
| cli-reachable-passthrough | 可达放行无副作用（spec「可达放行无副作用」）：monkeypatch _ensure_app_reachable 返回 (True, False, "已自动启动应用服务")，驱动真实验证管线 → 断言短路点不触发（VerifyEngine 照常创建并 run、场景正常执行）、STATE 不落 blocked、无 admin_invoke_request.json、无 verify_env_blocked 信号——与既有行为逐字节一致。 | pass | 0/5 | - |
| cli-user-blocked-guard | user_blocked 守卫放行（spec「预留判定位放行」）：monkeypatch _ensure_app_reachable 返回 (False, True, "需用户登录后重试")，驱动真实验证管线 → 断言不短路（VerifyEngine 照常 run）、不因守卫落 blocked、无 admin 呼叫——为将来「需用户参与」场景保留不误杀通道。 | pass | 0/5 | - |
| cli-two-rounds-frozen-escalation | 连续两轮不可达 → 冻结转人工（proposal「连续 2 轮冻结转人工」回归衔接）：同 spec 驱动两次（BLOCKED→TESTING 走既有复位 gate），monkeypatch 每次返回 (False, False, note) → 断言第一轮 blocked/_env_block_rounds=1/warning 信号、第二轮 frozen=true/_env_block_rounds=2/critical 信号——短路落 blocked 后既有升级通道的阈值语义不被破坏。 | pass | 0/10 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

