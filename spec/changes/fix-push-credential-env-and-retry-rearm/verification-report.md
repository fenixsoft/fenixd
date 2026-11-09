# 验证报告：fix-push-credential-env-and-retry-rearm

> ⚠️ 本报告由框架于 2026-11-09T09:58:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-09T09:58:02.899142+00:00+run-result@mtime1794218282943588236

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.02M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| git-env-smoke-import | 交付物落位与导入冒烟（tasks 1.1/6.1）：fenixd、core.event_bus、core.pm_engine.engine、core.systemd_hosting、core.git_env 全链导入通过，且 core.git_env.resolve_git_env 单源解析器可导入（收口冒烟命令逐字取自 tasks 6.1）。 | pass | 0/3 | - |
| push-retry-credential-behavior-tests | 推送凭证与续推行为测试面全绿（tasks 2.2/4.2/5.2 强制新建的 tests/test_push_retry_recovery.py）：覆盖 daemon env 无 HOME 时子进程 env 含注入 HOME、凭证文件在场命令含 helper 参数/缺席不含、启动凭证自检双腿皆缺告警一次/单腿可用不告警/探测异常不阻断、done 分支退避到期续推投递发生、退避期内 debug 跳过不发 push、计数达上限或 push_failed 已发不再投递、重启后（STATE 字段存量+退避已过期）首轮扫描拾取、executor 拒绝时扫描不中断、executor 缺席当轮 WARNING 跳过且无内联 approve_push 调用、多 spec 命中主循环不内联阻塞。空文件（no tests ran）以 exit_code=5 阻断假通过。 | pass | 0/2 | - |
| event-bus-done-branch-source-anchors | event_bus done 分支集成锚点（design D4 / tasks 5.1）：core/event_bus.py（现状 _recover_one 无 done 分支，实证于 core/event_bus.py:391-466）落位后须含 approve_push 续推复用、_is_push_backoffed 与 _get_push_retry_count 读侧单点复用（engine.py:5402/5404 静态转发）、[push_failed 耗尽升级标记判定面（event_bus 或 engine 侧）、_admin_executor 非阻塞投递面（getattr fail-open）——五个锚点现状 grep 计数均为 0，任一缺失即集成未落位。 | pass | 0/2 | - |
| push-credential-source-anchors | 凭证双腿与 HOME 基线源码锚点（design D2/D3 / tasks 2.1/3.1/3.2）：credential.helper=store --file= 单元素 helper 配置串须出现于 core/pm_engine/engine.py 或 core/git_env.py（现状 engine.py credential 计数 0）；core/pm_engine/engine.py 须消费 resolve_git_env（显式 env= 注入）；core/systemd_hosting.py 须含 resolve_git_env 单源取值与 Environment=HOME= 保底行（现状均 0）；bin/migrate_to_systemd.py 须新增 HOME 卫生结论（现状 grep -c HOME=0，实证有鉴别力）。 | pass | 0/2 | - |
| git-env-resolver-behavior-probe | resolve_git_env 单源解析序与凭证文件策略行为直测（design D1 / tasks 1.1/1.2）：env HOME 直取（设哨兵值鉴别 env 直取优先于 pwd）、无 HOME 走 pwd.getpwuid 回退、pwd 失败走 pm.push.credential_home 配置覆盖、三级全空安全回退不抛异常且不注入 HOME；credential_file 默认＝解析 HOME 下 .git-credentials、pm.push.credential_file 覆盖生效、显式置空字符串关断（credential_file 为 None/空）。契约字段名 resolved_home/process_env/credential_file 依 tasks 1.1。 | pass | 0/9 | - |
| approve-push-regression-tests | 既有推送语义回归（proposal Modified Capabilities 零改动约束 / push-ref-hygiene 不动）：tests/test_spec_approve_push.py 全绿——approve_push 实例级单飞锁、pushed 幂等跳过、远端 SHA 去重、退避级数 [300,900] 与 max_retries=3、push_failed 升级语义在本 SPEC 改动后保持不变（done 分支续推必须复用而非绕过这些语义，done-push-dedup 单飞纪律回归面）。 | pass | 0/2 | - |
| hosting-home-baseline-probe | HOME 基线行为直测、不依赖实现者自写测试（design D3）：①用 env 不含 HOME 的子进程作捕获源（sleep 探针），capture_env_candidate 产出的候选稿含 HOME=<pwd 解析值>（core/systemd_hosting.py:376，现状 HOME 无源进程候选稿无 HOME 键，本断言为本 SPEC 新增行为的鉴别信号）；②render_project_unit（core/systemd_hosting.py:430，现状模板仅 Environment=PATH 行 :469）渲染结果含 Environment=HOME=<pwd 解析值> 保底行。出处均为被测源码现行行号。 | pass | 0/5 | - |
| systemd-home-baseline-behavior-tests | 承载层 HOME 基线行为测试面全绿（tasks 3.1/3.3 扩展的 tests/test_systemd_env_path_hygiene.py）：候选稿缺 HOME 补齐并按 PATH 同款注释留痕、候选稿已含 HOME 时产物逐字节不变、render_project_unit 含 Environment=HOME=<resolved> 保底行且 env 文件覆盖语义不变（systemd 加载顺序）、迁移 plan 摘要输出 HOME 卫生结论行（「完整」或「补齐 <值>」）。 | pass | 0/2 | - |
| systemd-hosting-regression-tests | 既有 systemd 托管回归（task 6.1 关联面）：tests/test_systemd_hosting.py 全绿——PATH 基线行为（systemd-env-path-hygiene：PATH_BASELINE_DIRS 补齐/逐字节不变/unit PATH 保底行）在并列新增 HOME 基线后逐字节不变（proposal 明示 PATH 产物不动）。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

