# 验证报告：evo-add-verify-evidence-placement-contract

> ⚠️ 本报告由框架于 2026-10-03T21:15:29Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T21:15:28.779401+00:00+run-result@mtime1791062128811059167

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.03M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| evd-contract-default-fallback-and-override | 验证证据落位契约缺省与覆盖：default_evidence_dir 返回 .fenix/verify-evidence/<spec>/（spec 名替换）；resolve_evidence_dir 在契约显式声明 evidence_dir 时以契约为准，未声明/空值回退缺省模板；加载层对显式声明值原样载入。出处：core/verify_contract.py:154/:157/:272-283、tests/test_verify_evidence_placement.py::TestEvidenceDirContract | pass | 0/5 | - |
| evd-contract-illegal-value-warn-and-fallback | 契约 evidence_dir 非法值（绝对路径/含 ".." 段/非字符串等）加载层记 warning 并回退缺省 .fenix/verify-evidence/<spec>/，不静默生效也不抛异常。出处：core/verify_contract.py:506-531、tests/test_verify_evidence_placement.py::TestEvidenceDirContract | pass | 0/2 | - |
| evd-contract-chain-e2e-probe | 契约链端到端探针（真实临时项目）：.fenix/verify.yaml 声明 evidence_dir → load_verify_contract 加载 → resolve_evidence_dir 以契约为准 → 该值以主树绝对路径形态渲染进 prompt_builder 证据落位段；改写为非法绝对路径后回退缺省；字段缺省时 resolve 输出缺省模板 .fenix/verify-evidence/<spec>/。出处：core/verify_contract.py:272、core/agent_runner/prompt_builder.py:966 | pass | 0/2 | - |
| evd-template-declares-evidence-dir | verify.yaml 模板证据目录声明：模板以注释形态声明 evidence_dir（含缺省说明与非法值回退语义）；模板中取消注释的示例可解析且加载后 evidence_dir 生效；模板原样（保持注释）加载走缺省 evidence_dir。出处：core/verify_contract_template.yaml:102-108、tests/test_verify_evidence_placement.py::TestTemplateDeclaration | pass | 0/4 | - |
| evd-prompt-guidance-three-lanes | prompt_builder 证据落位契约段：缺省渲染主树绝对路径（项目根/.fenix/verify-evidence/<spec>/）与相对路径、MUST NOT 与 worktree 禁令明示；契约覆盖值渲染其主树绝对路径；非法契约值回退缺省渲染；注入点在统一收尾处覆盖 implementer/fast-track/verifier 三车道。出处：core/agent_runner/prompt_builder.py:620/:966-1001、tests/test_verify_evidence_placement.py::TestEvidencePlacementPrompt | pass | 0/5 | - |
| untracked-pure-untracked-fires-before-early-exit | untracked 散件信号基础闸门：tracked 零改动（:163-165 空集早退回归点）时纯 untracked 场景信号照常触发（插桩在 tracked 空集早退之前）且 tracked 口径仍返回 clean 形态；低于缺省阈值（4<5）不告警仅计时；admin.maintree_untracked_stray_threshold 配置可下调闸门。出处：core/worktree_manager/stray_wip.py:220-263/:481-538、tests/test_verify_evidence_placement.py::TestUntrackedSignal | pass | 0/4 | - |
| untracked-exemption-and-entry-level | untracked 豁免与 entry 级判定：.fenix/ 内 negation 放行项（!.fenix/verify.yaml）与已 ignore 路径（*.log）不计入清单与告警 evidence；混合目录（evidence/ 内已 tracked 条目 + 5 个 untracked 散件）只计 untracked 条目、已 tracked 条目不误报、目录不整体豁免（无忽略规则项目的兜底可见性）。出处：core/worktree_manager/stray_wip.py:398-446、tests/test_verify_evidence_placement.py::TestUntrackedSignal | pass | 0/3 | - |
| untracked-fingerprint-one-shot-evolution-reset | untracked 指纹生命周期：同指纹重复盘点一次性不重复告警；内容演化产生新指纹（路径排序集+逐文件内容 sha256）宽限未到不重告、滞留耗尽后新指纹照常升级（不被旧指纹 escalated_at 拖住）；指纹全部消失注册表自动复位，同指纹再现重新起算并可再告警。出处：core/worktree_manager/stray_wip.py:540-575、tests/test_verify_evidence_placement.py::TestUntrackedSignal | pass | 0/3 | - |
| untracked-dual-stream-merge-zero-touch | 双流并存与零触碰：tracked 散件（major）与 untracked 散件（info）同轮盘点各落各的 signal_type 与 severity、untracked 结果以附加键并入不干扰 tracked 口径既有键；盘点/告警前后 git status --porcelain 逐字节一致；git check-ignore 不可用时本轮保守放弃不告警。出处：core/worktree_manager/stray_wip.py:243-263/:448/:576、tests/test_verify_evidence_placement.py::TestUntrackedSignal | pass | 0/3 | - |
| untracked-threshold-grace-config-parsing | 阈值/宽限配置解析：admin.maintree_untracked_stray_threshold 缺省 5，非法值（非数/负值/NaN/inf/<1）一律回退缺省（阈值是降噪闸门，0 等同关闭降噪按配置事故回退），合法值生效；宽限复用 admin.maintree_stray_wip_grace_minutes（同族同语义，untracked 与 tracked 同键读取）。出处：core/worktree_manager/stray_wip.py:44-115、tests/test_verify_evidence_placement.py::TestThresholdAndGraceConfig | pass | 0/4 | - |
| untracked-e2e-lifecycle-probe | untracked 信号端到端生命周期探针（真实 git 仓 + 缺省阈值闸门，宽限配置 0 即耗尽升级）：5 个散件越缺省阈值 5 → sweep 告警落 AdminStore（signal_type=maintree_untracked_stray_stale、severity=info、spec 空、evidence 列路径）→ 同指纹重复盘点不重告 → 散件全部删除注册表复位（untracked 键消失）→ 散件再现重新起算再告警（共 2 条）。出处：core/worktree_manager/stray_wip.py:135-191/:481-538、core/admin_store.py | pass | 0/2 | - |
| admin-monitor-two-table-registration | admin_monitor 两表登记（只告警不处置降噪语义）：SIGNAL_SEVERITY 登记 maintree_untracked_stray_stale=info；SIGNAL_RECOMMENDATION 登记只告警不处置文案（含挪入 .fenix/verify-evidence/<spec>/ 的指引）；MUST NOT 收录 STORED_SIGNAL_TYPES（收录即被摄取循环无条件唤起人工，与 info 留痕语义相抵）；告警落 AdminStore 记录形态（kind/severity/spec/evidence 字段在案）。出处：core/admin_monitor.py:264-331/:364-415/:452、tests/test_verify_evidence_placement.py::TestAdminMonitorRegistration | pass | 0/5 | - |
| evd-prompt-baseline-and-report-gate-regression | 回归点：verifier 提示词逐字节 baseline（含新增证据落位段 _evidence_placement_section 拼接）零漂移、admin 结构化 evidence 渲染不回退（tests/test_agent_prompt_files.py）；verify_report 单文件入库 pathspec 零触碰（tests/test_verify_report_gate.py，proposal 非目标：不改动该 pathspec）。出处：tests/test_agent_prompt_files.py:250-268、tests/test_verify_report_gate.py | pass | 0/2 | - |
| regression-stray-sweep-and-verify-contract | 回归点：既有 maintree stray sweep 与 verify contract 相关测试零回退（test_maintree_stray_wip_sweep、test_verify_contract、test_verify_contract_template_preflight、test_verify_contract_autodraft、test_worktree_stray_and_identical）——tracked 口径现行行为逐字节不变、evidence_dir 增量不改契约既有语义。出处：tasks.md 3.2、tests/ | pass | 0/2 | - |
