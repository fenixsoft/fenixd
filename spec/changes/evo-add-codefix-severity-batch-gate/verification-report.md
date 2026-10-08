# 验证报告：evo-add-codefix-severity-batch-gate

> ⚠️ 本报告由框架于 2026-10-08T19:22:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T19:22:06.989457+00:00+run-result@mtime1791487327019099990

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.79M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| severity-gate-config-reader-matrix | 配置读取器矩阵：get_code_review_fix_config 新键 min_immediate_severity（缺省 major）与 minor_batch_cadence（缺省 7 天）——缺省段返回缺省值；合法值 minor/info/critical 原样生效（design §5 词表四档 info\|minor\|major\|critical，critical 为最严门限档）；真正词表外值（high/blocker/urgent/非字符串、cadence 0/负数/字符串）回退缺省不抛错；非法读取经 fenixd.config logger 走告警通道。出处：core/config.py:2276 词表校验、core/code_review.py:472 _SEVERITY_GATE_TIERS；judge 修复：原场景把 critical 标为「非词表值」与其自身 design §5 矛盾，按 design 修正断言。 | pass | 0/15 | - |
| select-batch-mixed-severity-split | 混合严重度选批分流：临时项目台账写入 2 major + 1 minor + 1 info 四条 open 条目（异文件、first_seen_at 锚取相对当下 1.5-3 天，确保 7 天周批组放行窗口未到期），调用 core.code_fix.select_batch 并经 severity_gate 形参显式注入门限 {'min_immediate_severity': 'major'}——当日批只纳入达门限 major 的条目，minor/info 被分流不出现在批内，且 major 组间保持 first_seen_at 升序。出处：core/code_fix.py:2014 select_batch 签名（severity_gate 形参，None=门限禁用系设计行为）、core/code_review.py:561 severity_gate_open；judge 修复：原探针自适应候选表漏真实形参 severity_gate（裸调 None 走门限禁用），且 first_seen_at 硬编码致周批窗口跨日到期。 | pass | 0/7 | - |
| generate-fix-spec-pure-minor-empty-batch | 手工通道绕过被拒：临时项目经 upsert_findings 落两条纯 minor/info open 条目（与 tests/test_code_review.py TestGenerateFixSpec 同款夹具路径），以与 Dashboard 手工通道相同的 core.code_review.generate_fix_spec 入口触发修复批——未到周批窗口时按空批处理：不生成 spec（spec_name 为空）、全部请求条目进入 skipped 且带非空原因说明。出处：core/code_review.py:1375 generate_fix_spec（候选筛选 :1422-1428 status==open 之上叠 severity 谓词）、spec.md「手工通道绕过被拒」场景。 | pass | 0/5 | - |
| chain-last-batch-deferred-aware | deferred 不误判链收敛：临时项目含 1 major + 1 minor open 条目（first_seen_at 锚取相对当下 1-2 天，确保 7 天周批组放行窗口未到期），select_batch 经 severity_gate 形参注入门限取得 major 批后调用 core.code_fix.is_chain_last_batch——剩余 minor 处于 severity-deferred 态被链末批判定同口径排除（判 True，链正常收敛而非空转）；对照分支：另留一条未 defer 的 major 不在批内时判 False。出处：core/code_fix.py:2080 is_chain_last_batch（severity_gate 形参同款注入）、core/code_review.py:561 severity_gate_open；judge 修复：原 gate_kwargs 候选表漏真实形参 severity_gate（批混入 minor、chain_last_true 系空真），且 first_seen_at 硬编码致窗口跨日到期。 | pass | 0/6 | - |
| severity-gate-unit-suite-green | 交付单测全绿：tests/test_code_fix_severity_gate.py（task 3.1 新建）在验证树上以 pytest -v 全量运行，退出码 0 且输出含 passed 汇总——覆盖出题探针无法直驱的时序类路径（deferred 跨周批晋级、deferred 期间同指纹合并刷新、链收敛统计不计 skipped/lost、门限配为最低档 info 时与现状零差异）。 | pass | 0/3 | - |
| user-config-scope-window-flip | 运维收尾核对（tasks 4.1）：用户级 /root/.fenix/config.yaml 的 admin.code_review.scope 由 full 回拨后，经 core.config.ConfigLoader.get_code_review_config 读取的生效值为 window（读取器口径：仅字符串 full 生效为 full，其余一律回退 window）。仅覆盖配置翻转；「次日核对评审 manifest 仅含窗口内变更文件」属次日动作，不在本轮验收。出处：core/config.py:2125 get_code_review_config scope 两档词表、core/admin_monitor.py:1538 生产读取点。 | pass | 0/2 | - |
| regression-code-review-suite | 回归点（code_review 侧）：core/code_review.py 改动（generate_fix_spec 候选谓词）不得破坏既有套件 tests/test_code_review.py——含 TestGenerateFixSpec 既有成功/幂等/skip 语义。 | pass | 0/2 | - |
| regression-code-fix-suite | 回归点（code_fix 侧）：core/code_fix.py 改动（选批 severity 分流）不得破坏既有套件 tests/test_code_fix.py（含 get_code_review_fix_config 既有键回退矩阵）与 tests/test_code_fix_affinity_batching.py（select_batch/is_chain_last_batch 既有选批与链末判语义）。 | pass | 0/2 | - |
