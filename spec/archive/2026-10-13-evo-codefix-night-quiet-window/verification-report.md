# 验证报告：evo-codefix-night-quiet-window

> ⚠️ 本报告由框架于 2026-10-05T18:50:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T18:50:06.695053+00:00+run-result@mtime1791226206726941505

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.78M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| nqw-delivered-testfile-green | 交付测试文件存在且全绿：pytest 跑 tests/test_code_fix_night_quiet_window.py 退出码 0 且打印 passed 汇总——任务 2.1 要求的窗内拦截/窗外放行/四点边界（04:14:59、04:15:00、04:44:59、04:45:00）/冷却叠加/配置关闭/非法降级全由该文件以注入时钟固定（spec/changes/.../tasks.md 2.1；锚点 core/code_fix.py:2813 checkpoint 守卫块 :2935-3010） | pass | 0/3 | - |
| nqw-inwindow-blocks-arms-once | 窗内拦截+武装告警恰一次：以必含当前本地时刻的单日窗配置驱动 checkpoint()，两次连续触发均返回 triggered=False、reason=night_quiet_window，且 AdminStore 中含窗区间 evidence 的武装告警恰好 1 条（首次进入武装才写，spec R3；验收「窗内触发不产生新批、武装告警可见」；锚点 core/code_fix.py:2935-3010、告警形态 :2301） | pass | 0/4 | - |
| nqw-end-boundary-release-alert | 窗末边界+解除告警：窗=[当前分钟, 当前分钟+1)，窗内 checkpoint 被拦且武装告警 1 条；真实时钟滚过窗末后首个 checkpoint 恢复投递（triggered=True），并落解除告警（含窗区间或新增告警记录，spec R3 解除对齐 :2341；验收「窗末首次触发恢复投递并落解除告警」；真实本地时钟驱动同时锚定 R6 本地时区——若实现误用 UTC 本场景必失败） | pass | 0/4 | - |
| nqw-start-boundary-allow-then-block | 窗起边界：窗=[当前分钟+1, 当前分钟+2)，当前时刻在窗前 checkpoint 正常放行（triggered=True）；真实时钟滚入窗后首个 checkpoint 被拦（reason=night_quiet_window）且武装告警恰 1 条——固定「起点含端点、窗前不拦」语义（spec R1/R3；锚点 core/code_fix.py:2935-3010） | pass | 0/4 | - |
| nqw-far-from-window-allows | 远离窗时正常投递：窗配置在当前本地时刻 +2 小时处（1 分钟宽，任何时刻都与 now 错开），checkpoint 正常放行且不写任何静默窗告警——固定「窗外不拦、无武装误报」（spec R1；锚点 core/code_fix.py:2935-3010） | pass | 0/3 | - |
| nqw-config-disabled-empty-and-off | 配置禁用：night_quiet_window 置空串与 off 两种取值下 checkpoint 均正常放行——「设为空串或 off 时完全禁用，行为与现状一致」（spec R2/验收；锚点 core/code_fix.py:2646 同款点号键读取模式） | pass | 0/4 | - |
| nqw-config-invalid-degrades-no-window | 非法配置降级：night_quiet_window 为 garbage / 25:00-26:99 / 04:15 / 04:15-04:60 四种坏值时 checkpoint 均按无窗处理正常放行且不写静默窗告警——「解析失败按无窗处理并 WARNING 一次」，配置事故不放大成停摆或误拦（design 判定点；spec R2；锚点 core/code_fix.py:2646 防御转换同款） | pass | 0/2 | - |
| nqw-cooldown-coexistence-later-wins | 与冷却共存取更晚者、互不复位：Case A 置冷却 8 秒后到期+静默窗更晚——冷却到期后 checkpoint 仍被拦且 reason=night_quiet_window（有效门=窗），禁用窗配置后放行；Case B 静默窗 1 分钟内到期+冷却 600 秒更晚——窗过期后仍被拦且 reason=switch_cooldown（有效门=冷却），清冷却态后放行。两方向各自独立武装/解除（spec R4；锚点 core/code_fix.py:2935-3010 冷却守卫与静默窗分支同级） | pass | 0/6 | - |
| nqw-default-config-window-active | 缺省窗生效：config 不含 night_quiet_window 键时走代码内缺省 "04:15-04:45"——探针按本地时刻自判期望分支（04:15-04:45 内被拦且 reason=night_quiet_window；窗外正常放行），两分支均确定性断言「不配置也有窗」（spec R2 缺省常量；锚点 core/code_fix.py:2646 同款缺省策略） | pass | 0/2 | - |
| nqw-three-path-convergence-checkpoint | 三路触发单点收敛（spec R5 不变量）：同一窗内配置下，批收尾自驱动 _resubmit（:3369）、持有者终态回调 _make_holder_retry_callback（:3643）、event_bus full-scan 末尾兜底（core/event_bus.py:274，stub state_machine 直达兜底点）三条路径均真实驱动 checkpoint() 被窗拦并留武装告警；另以 inspect 源码锚固定三处调用点均汇入 checkpoint 单点 | pass | 0/6 | - |
| nqw-adjacent-lanes-regression-green | 相邻车道回归：既有冷却车道测试（tests/test_codefix_conn_error_cooldown.py，37 例）与 api_timeout salvage 测试（tests/test_code_fix_api_timeout_salvage.py）全绿——固定非目标「不改 api_timeout 终局判定与 salvage、冷却语义不被静默窗分支破坏」（proposal 非目标；锚点 core/code_fix.py:2935-3010 同级新增不得扰动既有守卫） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

