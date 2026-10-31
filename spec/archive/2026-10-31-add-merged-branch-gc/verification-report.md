# 验证报告：add-merged-branch-gc

> ⚠️ 本报告由框架于 2026-10-28T02:33:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-28T02:32:59.031607+00:00+run-result@mtime1793154779084306581

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.71M |
| 本链增量 Token（输出） | 0.15M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gc-e2e-recycle-expired-merged | GC 核心·四条件齐备回收（真实 git 仓库端到端）：构造过期已合并实现分支 fenix/old-arch-1787000000（tip 10 天前、已并入 main、无 worktree、spec 不存在）与同条件验证分支 fenix/verify-old-arch-1787000001，跑一轮 cleanup_stale_worktrees 后两者均被 git branch -d 删除；宽限期内分支（tip 3 天前）与未合并分支（tip 10 天前）保留。base_dir 故意不创建，同时取证 tasks 2.1「分支 GC MUST NOT 被 worktree 清扫 base_dir early-return 静默跳过」（挂载点 stale_sweep.py:54）。出处 specs/merged-branch-gc/spec.md「四条件齐备的分支被回收/宽限期内分支保留/未合并分支永不进入删除」、tasks.md 2.1/2.2/4.2；驱动方式对齐 tests/test_daemon_lifecycle_races.py:1305 （WorktreeManager(base_dir, project_root, logger, state_reader=…) 构造，core/worktree_manager/lifecycle.py:122） | pass | 0/5 | - |
| gc-e2e-active-worktree-legacy-exemptions | GC 核心·四类豁免保留（真实 git 仓库端到端）：五条均已合并且 tip 超宽限期（10 天前）的分支——活跃 testing 状态 spec （fenix/cmd-center-1787000010，STATE.md 显式状态集）、reviewing 状态 spec（fenix/review-feat-1787000011，_branch_protected_by_state 保护集外的活跃状态，由守卫(ii)补齐）、在册 recovery legacy 登记分支（register_legacy 仅分支模式，core/worktree_manager/legacy_registry.py:23，宽限期内）、已登记 worktree 占用分支（create_worktree_on_branch 注册进活动集）四条 MUST 全部保留；无任何豁免的对照分支 fenix/plain-arch-1787000014 被删除（证明清扫轮确已执行）。出处 specs/merged-branch-gc/spec.md「活跃 spec 分支豁免」Requirement 四 Scenario、tasks.md 2.2；STATE 注入对齐 tests/test_daemon_lifecycle_races.py:1298 （StateMachine.add_spec + state_reader=sm.read_all） | pass | 0/6 | - |
| gc-e2e-observability-log-and-silent | GC 可观测性（真实 git 仓库端到端）：第一轮删除两条过期已合并分支 fenix/del-a-1787000020 / fenix/del-b-1787000021（另有宽限期内 1 条与未合并 1 条跳过），捕获 WorktreeManager 注入 logger 的全部日志，断言两条被删分支名均出现在日志中（有删除时输出结构化日志，删除清单含分支名）；第二轮复跑（仅剩宽限期内与未合并分支，零删除）断言日志条数零增长（零删除 MUST 静默）。出处 specs/merged-branch-gc/spec.md「有删除时输出结构化日志」「GC 运行可观测：零删除 MUST 静默」、tasks.md 2.4；日志捕获经构造注入 logger（lifecycle.py:122 第三参），不臆测日志文案格式、只断言构造分支名出现 | pass | 0/9 | - |
| config-template-and-dist-deliverables | 配置模板与前端产物交付检查：.fenix/config.template.yaml 的 worktree: 节含 branch_gc 注释块（grep 命中 branch_gc 与 retention_days 两键注释，tasks 1.2）；core/dashboard/static/dist 构建产物含 branch-gc-panel 标记（data-testid 字符串经打包保留，tasks 3.5 npm build 产物零陈旧——面板未进 dist 时 web 场景必然空转，此处机械前置拦截）。出处 tasks.md 1.2/3.5、.fenix/config.template.yaml:249（worktree: 节）、core/dashboard/static/config/config.ts:9（产物 hash 文件名，故用 grep -rq 目录级探测） | pass | 0/6 | - |
| config-parse-fallback-effective-view | 配置解析容错（stale_code_selfheal 同款口径，tasks 1.1）：向临时项目逐轮写入 7 种 worktree.branch_gc 配置形态并经 core.dashboard.data.read_effective_config（config_admin.py:909，既有稳定公开 API）读生效视图——合法值透传（enabled:false + retention_days:3 原样回读）、retention_days=0/负数/字符串/布尔（int-not-Bool 校验）回退默认 7、节非 dict（[1,2]）容错回退、enabled 非字符串布尔回退 true 且不影响 retention 合法值透传（逐键独立兜底）；全程不抛异常不硬失败。出处 specs/merged-branch-gc/spec.md「非法配置不致崩」「配置缺省即开启」、tasks.md 1.1/1.3 | pass | 0/10 | - |
| branch-gc-unit-suite-green | 交付测试文件全绿（tasks 1.3/2.5）：tests/test_branch_gc.py 存在且 pytest -v 全量通过——覆盖配置解析七态与 GC 判定（四条件齐备删除/宽限期内保留/未合并不删且计数/活跃 spec 豁免含 testing/reviewing/worktree 占用跳过/GC 关闭零动作/单分支 -d 失败不中断/解析失败跳过/零删除静默/legacy 登记跳过）。断言只锁 exit_code=0 与汇总 passed，不预登记具体用例名（测试文件由本轮实现交付，用例名以实测输出为准，避免臆测断言） | pass | 0/3 | - |
| stale-sweep-regression-suite-green | 既有清扫/分支保护回归网不被 GC 引入破坏（tasks 4.1 重点面）：运行既有 stale_sweep 与 worktree 清扫相关测试文件 tests/test_daemon_lifecycle_races.py、tests/test_interrupt_recovery_preserve.py、tests/test_reclaim_stale_autostash.py（cleanup_stale_worktrees 的在飞引用保护/孤儿清理/遗产回收既有行为），pytest -q 全绿（exit 0 + 汇总 passed；-q 单独使用不并列 -v，保证汇总行输出形态） | pass | 0/2 | - |
| cli-branch-gc-user-config-reset | 链首夹具·用户级 branch_gc 配置复位（场景文件缺陷自建前置）：GET /api/config 无参走 user scope 读 USER_CONFIG_PATH=~/.fenix/config.yaml（settings_routes.py:132 → read_config scope=user），前轮 write-roundtrip 经 POST 持久化的 worktree.branch_gc（enabled:false/retention_days:14）跨 run 残留，会让下游 api-branch-gc-default-echo 的缺省回显断言读到脏值。本场景在链首移除该节恢复「无 branch_gc 配置」缺省态（config_admin.py:959 缓存键含 USER_CONFIG_PATH 文件签名，复位即对 API 生效）；文件不存在或无该节视为已复位。幂等：重复执行无副作用 | pass | 0/3 | - |
| api-branch-gc-default-echo | 配置缺省回显（tasks 3.1 默认回显视图 / spec「配置缺省即开启」）：GET /api/config（用户级，core/dashboard/routes/base.py:715）在无 worktree.branch_gc 配置时回显默认生效值 worktree.branch_gc.enabled=true、retention_days=7。链首场景：本链后续写场景依赖此时序，放最前保证读的是缺省态。前置自建（本轮裁决修复）：依赖链首夹具 cli-branch-gc-user-config-reset 先移除 ~/.fenix/config.yaml 的 worktree.branch_gc 残留节，保证读到缺省态 | pass | 0/3 | - |
| api-branch-gc-write-roundtrip | 配置写回通道往返（tasks 3.1 受管键注册 + spec「Dashboard 面板读写配置」后端通道）：POST /api/config（base.py:777）提交 {worktree:{branch_gc:{enabled:false, retention_days:14}}} → 200 且 saved=true、响应回写视图含新值；再 GET 确认落盘持久（false/14）。出处 tasks.md 3.1（键清单/写入校验）、core/dashboard/data/config_admin.py:1443（write_config 受管 patch 写回，保留非受管键） | pass | 0/5 | - |
| api-branch-gc-invalid-retention-rejected | 写入校验谓词（tasks 3.1：retention_days int-not-bool 且 ≥1）：POST /api/config 提交 retention_days=0 → 400 拒绝（对齐 stale_code_selfheal 前置校验形态，config_admin.py:1991），错误信息含 retention_days 字样；随 GET 确认非法值未落盘（仍为上一轮合法值 false/14）——非法配置不致崩、不改写既有生效值。出处 specs/merged-branch-gc/spec.md「非法配置不致崩」、tasks.md 3.1 | pass | 0/4 | - |
| web-branch-gc-echo-persisted-off | 面板回显持久化值（tasks 3.3 回显当前生效值，跨 kind 状态传递）：经 api 链写入的 enabled=false 在设置页分支 GC 面板回显为关（Switch aria-checked=false）；面板根/开关/宽限期输入可见、保存按钮可用。选择器契约按同页面最近邻面板惯例（StaleCodeSelfhealPanel.tsx:77/87/121 的 data-testid 三件套与 MiscSettingsPanel.tsx:155 保存键，本 SPEC 新建 BranchGcPanel.tsx 对齐该族谱：branch-gc-panel / branch-gc-control-enabled / branch-gc-field-retention_days / branch-gc-save）。navigate 出处：/#/settings（core/dashboard/static/src/app.tsx:136 路由 + core/dashboard/static/config/config.ts:15 hash 路由），菜单页签以「分支」文案定位（tasks 3.4 注册到设置页） | pass | 0/6 | - |
| web-branch-gc-save-roundtrip | 面板保存回路（tasks 3.3 保存走既有配置写回通道）：打开开关（false→true）并把宽限期改为 9 天后点保存，断言保存动作触发 /api/config 网络写回（expect_network 挂在保存点击步骤）、开关态翻转为 aria-checked=true、保存按钮可点且未被遮挡。输入内容正确性由下游 api-branch-gc-web-save-persisted 经 GET 读回 9 机械闭环（InputNumber 受控值为 DOM property 非 attribute，不做脆弱的 DOM 值回读）。navigate 出处同上（app.tsx:136 + config.ts:15） | pass | 0/5 | - |
| api-branch-gc-web-save-persisted | web 保存落盘闭环（跨 kind 链收口）：GET /api/config 读回 web-branch-gc-save-roundtrip 经面板保存的值——worktree.branch_gc.enabled=true、retention_days=9，证明前端表单值经既有写回通道完整落盘（tasks 3.3）。出处 core/dashboard/routes/base.py:715 | pass | 0/3 | - |
| web-branch-gc-invalid-input-blocked | 面板非法输入拦截（tasks 3.3 宽限期最小 1 + spec「非法配置不致崩」前端口径）：宽限期输入 0 后点保存，antd 表单校验错误提示在面板内可见（.ant-form-item-explain-error，同族面板校验失败渲染 explain-error 的既定形态，StaleCodeSelfhealPanel.tsx:68 注释与 rules min:1 先例），保存按钮仍可交互；非法值不得发出写回（持久化不变由下游 api-branch-gc-invalid-ui-input-not-persisted 机械闭环）。navigate 出处同上（app.tsx:136 + config.ts:15） | pass | 0/4 | - |
| api-branch-gc-invalid-ui-input-not-persisted | 非法 UI 输入零落盘（web-branch-gc-invalid-input-blocked 的机械收口）：GET /api/config 确认宽限期仍为 9、开关仍为 true——前端校验拦截的 0 未进入写回通道（tasks 3.3 最小 1 约束的持久化侧证据）。出处 core/dashboard/routes/base.py:715 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 新增场景 cli-branch-gc-user-config-reset（重新规划，第 1 轮）

