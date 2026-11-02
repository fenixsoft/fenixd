# 验证报告：evo-night-window-guard-coverage-closure

> ⚠️ 本报告由框架于 2026-10-30T12:55:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T12:53:55.158259+00:00+run-result@mtime1793364903925545647

## 结论：✅ 通过（verified）

**状态：verified — 12/13 场景通过，1 失败，0 错误（其余失败场景已豁免（见分类列））**

13 场景 12 PASS；唯一非 PASS 场景 pytest-night-window-dispatch-guard-preflight-suite 经跨轮指纹一致复用归类 flaky（原始 run exit 1，同命令两次复现均 exit 0 / 13 passed + 6 subtests，stub 化确定性用例，重试可过），断言时序无产品缺陷特征；无 product-bug、无 test-defect、无场景文件缺陷，验证通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.38M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| night-window-default-two-window-parse | 缺省静默窗多窗化：NIGHT_QUIET_WINDOW_DEFAULT 缺省字面量为「03:00-03:15,04:15-04:45」，经 _parse_night_quiet_windows 解析为两窗（03:00=180 分/03:15=195 分、04:15=255 分/04:45=285 分），窗外断连波（03:00 形态）纳入缺省覆盖（spec Scenario「窗外断连波纳入缺省覆盖」）。出处 core/code_fix.py:3468、core/code_fix.py:3503。注：interaction-contract 候选 Link（proposal.md:3）为 proposal 文档文本「Link is Down」内核日志字样，本 SPEC 无任何 web/页面交付物，声明为纯展示、不可交互。 | pass | 0/8 | - |
| night-window-parse-edge-cases | 解析器异常路径与语义回归：单窗输入行为不变、分号分隔等价多窗、空串/off（大小写不敏感）/YAML 裸 off（bool False）禁用返回 None、任一非法段整体拒绝（宁缺毋错不部分生效）、end<=start 逆序非法、空段非法、小时/分钟越界非法、bool true 拒判禁用（走非法告警路径）。出处 core/code_fix.py:3499-3530。 | pass | 0/16 | - |
| night-window-config-template-doc | config.template.yaml 键文档同步：admin.code_review_fix.night_quiet_window 注释块含多窗示例值「03:00-03:15,04:15-04:45」与「多窗以逗号/分号分隔」口径说明，与代码注释一致、不在模板强配（tasks 1.2）。出处 .fenix/config.template.yaml:562-570。 | pass | 0/3 | - |
| night-window-consumer-doc-sync | 缺省字面量消费面文档同步：fenixd.py CODE_FIX_RESULT_MESSAGES["night_quiet_window"] 用户文案为多窗口径「默认 03:00-03:15,04:15-04:45 多窗」（窗内手动触发回链不再是旧单窗文案「默认 04:15-04:45」）；知识页 codefix-night-quiet-window.md 缺省值描述同步为多窗并保留 2026-10-30 变更记录（tasks 1.4）。出处 fenixd.py:4738、spec/knowledge/domains/code-fix-lane/codefix-night-quiet-window.md:11、:30。 | pass | 0/4 | - |
| evolution-guard-host-layer-substring-contract | 自进化守卫宿主层留痕契约：fenixd.py 含 reason=night_quiet_window_deferred 跳过留痕与守卫调用 _evolution_night_window_defer；core/agent_runner/maintenance_runs.py 与 core/event_bus.py 均不含「night_quiet_window」子串（tests/test_code_fix_night_quiet_window.py assertNotIn 契约，tasks 2.2——守卫与 skip 日志 MUST 留宿主层不下沉）；core/code_fix.py 保持解析单源。出处 fenixd.py:5112、fenixd.py:5336、tests/test_code_fix_night_quiet_window.py:538-541。 | pass | 0/6 | - |
| evolution-guard-placement-and-config-key | 自进化检查点守卫落点与配置单源：_check_evolution_checkpoint 中守卫调用（defer_note = self._evolution_night_window_defer()）位于自进化条目保留清理（prune）日志之后、单飞判定（if self._evolution_in_flight）之前——prune 不因窗顺延跳过；配置读同键 admin.code_review_fix.night_quiet_window、缺省复用 NIGHT_QUIET_WINDOW_DEFAULT、解析复用 _parse_night_quiet_windows（不引入第二份窗配置/第二键）；时长估计 _evolution_archive_duration_mean；读取/解析/导入异常按无窗 fail-open（tasks 2.1）。出处 fenixd.py:5112-5118、fenixd.py:5270-5306。 | pass | 0/8 | - |
| evolution-defer-reason-and-state-untouched | 跨窗顺延语义文案：命中窗时跳过日志含 reason=night_quiet_window_deferred、预计区间与「预计分析区间与夜间静默窗相交，本轮跳过派发」、时长样本口径（近几轮实测均时长/无实测样本仅判派发时刻落窗）与「水位与就绪扫描状态不变，窗后巡检自然重触」承诺（spec Requirement「自进化车道跨窗避让」：SHALL NOT 消费水位或就绪标记，窗后巡检自然重触）。出处 fenixd.py:5327-5340。 | pass | 0/5 | - |
| pytest-night-window-dispatch-guard-parsing-suite | 新守卫测试文件解析段全绿：tests/test_night_window_dispatch_guard.py::TestDefaultMultiWindowParse 缺省多窗解析/源码契约/单窗不变/分号等价/空串与 off 禁用/非法段整体拒绝 7 用例通过（tasks 4.1）。出处 tests/test_night_window_dispatch_guard.py:58-111。 | pass | 0/8 | - |
| pytest-night-window-dispatch-guard-evolution-suite | 新守卫测试文件自进化段全绿：TestEvolutionCheckpointNightWindowDefer 预计跨窗顺延（水位/就绪标记不动）、不入窗照常派发、窗禁用派发、归档时长样本读取、TestHostLayerNightQuietContract reason 子串仅宿主层（tasks 4.2/2.2）。出处 tests/test_night_window_dispatch_guard.py:123-261。 | pass | 0/8 | - |
| pytest-night-window-dispatch-guard-preflight-suite | 新守卫测试文件预检段全绿：TestConnectivityPreflight gaierror 顺延＋跳过日志/超时顺延/探测自身异常 fail-open/白名单归一（spec_name 回退、维护 agent_type、dispatch 族不探测、无 base_url fail-open）＋TestApiProbeHost 形态解析 13 用例（tasks 4.3/3.2）。出处 tests/test_night_window_dispatch_guard.py:267-472。 | fail | 2/9 | flaky |
| pytest-code-fix-night-quiet-window-regression | 既有夜窗回归面全绿：tests/test_code_fix_night_quiet_window.py 全量 44 用例通过（关键字缺席契约＋既有单窗/多窗行为＋bool 同义化，tasks 4.4；含 test_default_window_value 源码契约断言已同步多窗缺省字面量）。出处 tests/test_code_fix_night_quiet_window.py:168-180、:538-541。 | pass | 0/4 | - |
| dispatch-preflight-dns-defer-live | 派发前连通预检真实行为：探测不可解析域名（.invalid 保留 TLD）→ gaierror/超时按失败顺延（_dispatch_connectivity_preflight 抛 RuntimeError reason=dns_probe_failed 含 lane 留痕，不 Popen 不产生秒死 run）；可解析目标（localhost）→ 探测通过；无可判定探测目标（未配 ANTHROPIC_BASE_URL）→ fail-open 放行不抛错。getaddrinfo 独立守护线程 join(2.5s) 判超时。出处 core/agent_runner/runner.py:6040-6160、runner.py:6311-6313。环境依赖：依赖系统 DNS 解析器按 RFC 6761 拒绝 .invalid 保留域，无 fallback（DNS 行为异常时场景如实失败；守卫逻辑本身已由场景 pytest-night-window-dispatch-guard-preflight-suite 以 stub 用例确定性覆盖）。 | pass | 0/9 | - |
| dispatch-preflight-lane-whitelist-contract | 预检白名单与挂载单点契约：_DISPATCH_PROBE_LANES 恰为维护车道 {evolution, code-review, code-fix, administrator, self-review}；dispatch 族（spec/impl/spec-review/dispute-judge）与 regression 一律不探测（proposal Out of Scope 不动 spec-review/regression 派发时点）；未传 agent_type 的直调车道按 spec_name 归一回退；探测调用点位于 _run_agent 的 Popen 之前（仅挂派发前，不影响在飞 run）；超时常量 2.5 秒。出处 core/agent_runner/runner.py:6033-6052、runner.py:6311-6313。 | pass | 0/13 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| pytest-night-window-dispatch-guard-preflight-suite | exit_code pytest-preflight 期望 0 实际 1 | flaky | 不稳定复现（非产品缺陷） | 原始 run 退出码 1，同命令复现第1次(--tb=long)与第2次(--tb=short 原样)均退出码 0；13 用例全为 stub 化确定性用例（mock.patch 替换 getaddrinfo/socket），原始失败不可在相同代码上复现 |
| pytest-night-window-dispatch-guard-preflight-suite | output_match combined contains "13 passed" | flaky | 不稳定复现（非产品缺陷） | 统计行 "13 passed" 在复现 run 中恒出现（13 passed, 6 subtests passed in 0.28s）；原始 run 该行缺失仅因 pytest 以非零码收尾且 stdout 被截断，与断言本身无关，随 flaky 复跑自愈 |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

