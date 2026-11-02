# 验证报告：evo-add-night-window-bool-normalization

> ⚠️ 本报告由框架于 2026-10-30T10:26:24Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T10:26:22.814535+00:00+run-result@mtime1793355982870918484

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.11M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| night-window-parse-single-source-bool-semantics | 解析单源布尔同义化直测：真实驱动 core/code_fix.py 的 _night_quiet_window_disabled/_parse_night_quiet_windows，验证布尔 false 与字符串 off 同义（守卫显式停用）、布尔 true 拒判为非法（不停用、走告警路径）、解析在 str() 化之前判原始 bool，同时回归合法多窗/非法窗形态解析不变。出处 core/code_fix.py:3356-3415 | pass | 0/18 | - |
| night-window-parse-unit-tests | 交付测试回归：运行 tests/test_code_fix_night_quiet_window.py::TestBoolWindowNormalization （1.1 解析单源布尔语义三用例：false→禁用语义、布尔 true 拒判告警一次不提醒、单源语义表），全部 PASSED 且零失败。出处 tests/test_code_fix_night_quiet_window.py:964-1037 | pass | 0/5 | - |
| night-window-load-time-lint-unit-tests | 交付测试回归：运行 tests/test_code_fix_night_quiet_window.py::TestLoadTimeLint （1.2 载入期 lint 三用例：布尔 true 告警一次/进程、非法字符串告警、合法与缺省形态静默），全部 PASSED 且零失败。出处 core/config.py:3050-3096 | pass | 0/5 | - |
| night-window-config-lint-live-warning | 载入期 lint 直驱验证：真实调用 ConfigLoader._maybe_warn_invalid_night_quiet_window，验证缺省键/合法形态（布尔 false、off、单窗、多窗）静默；布尔 true 出一次性 WARNING 且文案含非法值、合法形态说明与三守卫消费点全部停用警示；同进程重复调用与换非法值均被进程级去重抑制（一次性语义）。出处 core/config.py:763/827/3050-3096 | pass | 0/7 | - |
| night-window-admin-parity-unit-tests | 交付测试回归：运行 tests/test_code_review_night_defer.py::TestBoolWindowAdminParity （1.3 消费点告警对等四用例：审查顺延车道布尔 false 不告警放行、布尔 true fail-open 同文案告警、两消费点共享进程级去重、admin 避让块原因点布尔 false 无告警），全部 PASSED 且零失败。出处 core/admin_monitor.py:1420-1447/2097-2104/6358-6364 | pass | 0/6 | - |
| night-window-admin-parity-live-warning | admin 车道告警对等直驱验证：真实调用 core/admin_monitor.py 的 _warn_night_quiet_window_invalid，验证停用态（布尔 false/off/空串）零告警（对等口径排除）；布尔 true 告警一条且文案与 code-fix 车道同款（admin 夜间静默窗配置非法、HH:MM-HH:MM 合法形态、按无窗处理）；同值去重、值变更重新告警。出处 core/admin_monitor.py:1417-1447 | pass | 0/7 | - |
| night-window-disabled-reminder-unit-tests | 交付测试回归：运行 tests/test_code_fix_night_quiet_window.py::TestDisabledDailyReminder （2.1 停用态每日提醒四用例：按（窗值,自然日）节流至多一条、值变更重提醒、跨自然日重提醒、有窗/非法值零提醒防双重告警源），全部 PASSED 且零失败。出处 core/code_fix.py:3599-3637/4132-4178 | pass | 0/6 | - |
| night-window-disabled-reminder-live-write | 停用态提醒落盘直驱验证：真实调用 _write_night_quiet_window_disabled_reminder 写入 /tmp 临时项目根，验证 .fenix/admin_alerts.json 落盘一条 signal_type=code_fix_night_quiet_window 的 SIGNAL 记录，文案为停用态专用（守卫停用中，非武装告警「进入静默窗」语义）、severity=warning、source=code-fix-lane、evidence 含窗值与提醒日。出处 core/code_fix.py:3599-3637/3452 | pass | 0/10 | - |
| night-window-full-suite-regression | 全量回归点：完整运行两交付测试文件（tests/test_code_fix_night_quiet_window.py 44 用例含既有 off/空串禁用、四边界武装、多窗门控等存量语义 + tests/test_code_review_night_defer.py 14 用例），验证布尔同义化落地后既有守卫语义零回归（44 passed, 14 subtests passed / 14 passed）。出处 tests/test_code_fix_night_quiet_window.py、tests/test_code_review_night_defer.py | pass | 0/9 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

