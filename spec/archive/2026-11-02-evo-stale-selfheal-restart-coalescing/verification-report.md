# 验证报告：evo-stale-selfheal-restart-coalescing

> ⚠️ 本报告由框架于 2026-10-30T13:12:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:12:57.872030+00:00+run-result@mtime1793365977929807487

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.11M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| coalesce-first-edge-base-gate | 「首启陈旧按基础闸重启」：无历史记录（空状态）时首个陈旧边沿按 idle_confirm_seconds=600s 基础闸确认——599s 空闲不触发、600s 触发写 restart_request 并记合流静止期参考时刻（最近重启时刻）；陈旧持续为真不产生新边沿、闸值不逐 tick 递增。出处：fenixd.py:520-524（合流内存态）、fenixd.py:2536-2557（_coalesce_note_edge 边沿登记）、fenixd.py:2683（tick 调用）、tests/test_stale_selfheal_coalescing.py:144-165 | pass | 0/3 | - |
| coalesce-second-batch-coalesce-gate | 「合流期内后续边沿按合流闸等待」（复刻 2026-10-18 五连重启窗形态）：基础闸重启后 1200s（<1800s 静止窗）第二批边沿须按 coalesce_idle_seconds=1800s 等待——600s 空闲不得再触发（既有病根回退点）、第三批落于等待窗内被同一轮吸收、末批后连续空闲达 1800s 收敛，三批连发仅两轮重启。出处：fenixd.py:2530-2536（_coalesce_effective_confirm 合流闸升格）、fenixd.py:2899-2922（收敛收尾）、tests/test_stale_selfheal_coalescing.py:168-201 | pass | 0/2 | - |
| coalesce-reset-after-quiescence | 「边沿消化后合流复位」回归点：按闸重启导致的悬置消化不复位合流态；悬置消化但静止期未届满时合流态保留；消化且距最近边沿/重启达 1800s 无新边沿才复位（记「合流期复位」日志），复位后首个陈旧重新按 600s 基础闸确认（599s 不触发/600s 触发）。出处：fenixd.py:2505-2528（_coalesce_maybe_expire 复位条件）、fenixd.py:2619-2623（消化期维护）、tests/test_stale_selfheal_coalescing.py:204-234 | pass | 0/2 | - |
| coalesce-restart-history-derivation | 「重启后合流态幂等延续」（进程更替双向防错）：内存合流态丢失后由 restart_history.jsonl 最近自愈重启记录幂等推导（每进程至多一次）——400s 前记录（<1800s 窗内）延续合流态、窗内新边沿按合流闸处理不回退 600s；1900s 超窗记录按新周期基础闸；无记录（首启空状态）按基础闸；内存复位后旧历史不得重新置位。出处：fenixd.py:2483-2503（_coalesce_derive_from_history）、tests/test_stale_selfheal_coalescing.py:371-428 | pass | 0/5 | - |
| coalesce-preflight-bypass-gate | 「preflight 请求通道不经合流闸」：合流闸等待中（自愈 600s 空闲不触发）关键路径经 code_stale_flag.request_restart 显式请求重启按既有语义立即成写；请求在场后自愈 tick 识别 in-flight 不重复写入、不产生第二轮自愈重启历史。出处：core/code_stale_flag.py:82（request_restart）、fenixd.py:2703-2704（in-flight 识别）、tests/test_stale_selfheal_coalescing.py:237-260 | pass | 0/2 | - |
| coalesce-dangling-force-override | 「悬空强转兜底不失效」异常路径兜底：合流闸等待中悬空满 4h（max_dangling_seconds=14401s）按既有强转逻辑立即重启（记「悬空超时触发」 WARNING），合流闸不得拦截；持续连发（批间隔恒 <1800s）下合流闸持续不满足时由 4h 强转收尾——修复生效延迟的绝对上界是 max_dangling_seconds。出处：fenixd.py:2899（合流闸不拦截强转）、fenixd.py:2884/:2955（_coalesce_note_restart）、tests/test_stale_selfheal_coalescing.py:263-291 | pass | 0/3 | - |
| coalesce-edge-convergence-logs | 「合流等待日志留痕」设计观测面验证：每次合流期内检出的边沿记 info「stale coalesce: 第 N 次边沿等待，闸值 Xs」（边沿 1→600 基础闸、边沿 2→1800 合流闸），陈旧持续为真不重记（每次边沿恰一条不刷屏）；执行重启时 WARNING 记合流收敛结果（本周期共 N 次陈旧边沿、合并为 1 次重启）。出处：fenixd.py:2551-2557（边沿日志）、fenixd.py:2911-2922（收敛日志）、tests/test_stale_selfheal_coalescing.py:336-368 | pass | 0/4 | - |
| coalesce-config-key-default-override-invalid | 「stale_code_selfheal.coalesce_idle_seconds 配置键」（Task 1.2，含异常路径）：缺省 1800；项目级显式覆盖 900 优先且实际收缩合流闸（899s 不触发/900s 触发）；bool 陷阱/0/负数/字符串/None/非整值浮点一律回退缺省不抛异常（0 不等效关闭）；节非 dict 按缺省降级。出处：core/config.py:2220-2229（缺省常量与动机注释）、core/config.py:2370-2374（_stale_selfheal_positive_int 归一读取）、tests/test_stale_selfheal_coalescing.py:296-333 | pass | 0/5 | - |
| coalesce-regression-cooldown-unchanged | 「防循环冷却语义不变」回归点：冷却滑窗（1800s 内 ≥3 次）仍按实际重启次数计数、合流等待不视为豁免——既有冷却/空闲判定套件 31 条在合流实现并存下全量通过（该套件基线配置已含 coalesce_idle_seconds 键同跑，tests/test_stale_selfheal_cooldown.py:126）。出处：fenixd.py:2600-2608（冷却判定不动）、spec scenario 7 | pass | 0/2 | - |
| coalesce-regression-existing-selfheal-suite | 回归点（既有行为操作前后对比）：既有陈旧自愈套件 50 条全过——含配置缺省节（断言含 coalesce_idle_seconds=1800，tests/test_stale_code_selfheal.py:847-866）、/api/config 配置读写往返、悬空 4h 强转、supervisor 熔断，证明合流增量未破坏既有自愈语义与配置面。 | pass | 0/3 | - |
| coalesce-full-suite-total-count | 正向路径汇总（防用例被跳过/漏跑）：交付的 tests/test_stale_selfheal_coalescing.py 全文件一把过，18 条用例（Task 2.1+2.2 全覆盖）exit 0 且总数恰为「18 passed」。出处：tasks.md Task 2.1/2.2、tests/test_stale_selfheal_coalescing.py | pass | 0/3 | - |
| api-config-echo-coalesce-default | 运行实例配置回显端点验证（混合交付拆分：配置键经被测应用端点传递）：GET /api/config（用户级生效配置）返回 200，stale_code_selfheal 节含新增 coalesce_idle_seconds 且为缺省 1800，idle_confirm_seconds 保持 600、enabled 缺省开启——新键经 read_config 生效值回显进入端点响应，证明配置键在运行实例真实生效面可见。出处：core/dashboard/routes/base.py:666（路由注册）、core/dashboard/routes/settings_routes.py:115-136（_api_config_get→read_config）、core/dashboard/data/config_admin.py:926（read_config 回显 get_stale_code_selfheal_config）、core/config.py:2370-2374 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

