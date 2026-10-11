# 验证报告：evo-add-key-path-stale-code-preflight

> ⚠️ 本报告由框架于 2026-10-11T17:45:43Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-11T17:45:43.210631+00:00+run-result@mtime1791740743244099257

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.88M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| flag-registry-failopen-unregistered | R1 陈旧旗标注册表 fail-open：fresh 进程直接 import core.code_stale_flag（不经 daemon），未注册时 is_stale() 返回 False（不陈旧）；同时验证注册表落 core 侧（模块源码无反向 import fenixd，core←daemon 单向）。出处：spec/changes/evo-add-key-path-stale-code-preflight/specs/key-path-stale-preflight/spec.md R1；tasks.md 1.1 | pass | 0/4 | - |
| flag-registry-register-query | R1 注册→查询主链：register(is_stale 回调) 注册返回 True 的回调后 is_stale() 为 True，注册返回 False 的回调后 is_stale() 为 False（两个独立子进程分别探，规避未规定的重复注册覆盖语义）。出处：tasks.md 1.1「register(is_stale 回调) / is_stale() 查询」 | pass | 0/4 | - |
| flag-registry-thread-safety | R1 线程安全 smoke：多车道线程并发读 is_stale() 与检测线程并发 register（写）交错压测，全程无异常。出处：tasks.md 1.1「线程安全（daemon 检测线程写、车道线程读）」 | pass | 0/2 | - |
| daemon-side-flag-sync-wiring | tasks 1.2 daemon 侧接线取证：fenixd.py 引用 code_stale_flag 注册表（启动初始化与 _update_stale_code_state 检测点同步旗标的最低限文本证据，只做旗标转发不改既有判定）。出处：fenixd.py:1359 _update_stale_code_state；fenixd.py:386 self._code_stale 初始化 | pass | 0/2 | - |
| keypath-preflight-delivery-tests | R2/R3 关键路径预检行为验收：交付测试文件 tests/test_key_path_stale_preflight.py 全量通过（SPEC 明文规定的测试内容——注册/查询/fail-open 三态；三个关键路径旗标置位时各产生 WARNING、restart_request 被创建且动作返回值与产物和不预检时一致；restart_request 已存在时不重复写不刷 mtime；旗标未置位零新增副作用）。出处：tasks.md 3.1；spec.md R2/R3/验收 1-3 | pass | 0/2 | - |
| keypath-insertion-points-wired | R2 三挂点接线取证：verification-report 收尾提交（core/pm_engine/engine.py）、蒸馏派发（core/knowledge.py）、admin choice 执行（core/admin_monitor.py）三个关键路径模块各自引用 code_stale_flag 预检（import 查询的最低限文本证据）。出处：spec.md R2；design.md 挂点清单——core/verify_report.py:987 _commit_verification_report、core/knowledge.py:968 dispatch、core/knowledge.py:1413 dispatch_distill、core/admin_monitor.py:6964 _apply_choice_execution | pass | 0/4 | - |
| stale-selfheal-regression | 验收 4 回归保障：既有陈旧自愈测试 tests/test_stale_code_selfheal.py 全量通过（自愈触发、空闲阈值、悬空超时、告警分级行为不变）。出处：spec.md 验收 4；tasks.md 3.2 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

