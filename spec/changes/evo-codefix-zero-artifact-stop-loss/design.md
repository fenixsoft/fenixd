# 设计：codefix-zero-artifact-stop-loss

## 落点

1. core/agent_runner/maintenance_runs.py（:3172-3183 硬门拦截点、:3226-3230 CodeFixResult 信封）：_check_code_fix_artifact 判定零产物失败时在信封置 failure_category="artifact_missing"，随既有失败信封路径返回。
2. core/code_fix.py（:6413-6447 首轮 run 失败收尾块）：读取信封 failure_category，按批指纹累计 artifact_missing 连败（进程内批级计数即可，形态对齐 :6499-6510 anomaly_streak 先例）；≥2 触发止损：该指纹标记跳过＋WARNING/告警留痕。
3. agents/code-fix.md：只读引用，作为契约测试的断言对象（:45-56 同步派发契约段，9ccf90158/4c2fc3a9d 现状基线）。
4. tests/test_codefix_zero_artifact_breaker.py（新建）：
   - 信封类别透出单测（伪造硬门零产物失败）；
   - 止损状态机单测（1 次不触发/2 次触发/其他类别不计数/触发后跳过并留痕）；
   - agents/code-fix.md 契约断言（参照 tests/test_prompt_lane_efficiency_sections.py:73-81 先例）。

## 风险与权衡

- 与 add-codefix-parse-error-breaker（在途）的 anomaly_streak 同域不同类（parse-error vs artifact_missing），计数互不干扰，避免误伤合法重试。
- 止损只停「同指纹零产物」形态，不影响其他失败类的既有重试预算。
- 指纹粒度沿用批链既有指纹定义，不新造指纹体系。