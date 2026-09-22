# 验证报告：add-declaration-relocation-protocol

> ⚠️ 本报告由框架于 2026-09-18T08:03:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T08:03:40.357667+00:00

## 结论：✅ 通过（verified）

**状态：verified — 34/34 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 34/34 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 34 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.79M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| resolve-main-tree-fallback | 无 branch/worktree 时读主树 tasks.md，source=main，deliverables/references 正确 | pass | 0/2 | - |
| resolve-branch-preferred | 分支声明与主树不同时以分支为准（source=branch，deliverables 为分支版本） | pass | 0/2 | - |
| resolve-branch-fallback-main | 分支不存在时回退主树（source=main，deliverables 为旧版本） | pass | 0/2 | - |
| resolve-empty-when-no-spec | 不存在的 spec 返回空结果（source=None，deliverables/references/entries 均空） | pass | 0/2 | - |
| resolve-worktree-preferred | worktree 版本优先于分支版本（source=worktree，deliverables 为 worktree 版本） | pass | 0/2 | - |
| resolve-no-declaration-returns-empty | tasks.md 无 Deliverables 段时回退后返回空（无声明段语义，守卫跳过） | pass | 0/2 | - |
| resolve-isomorphic-with-extract | resolve_result 与 extract_declared 输出结构同构（deliverables/references 两桶一致） | pass | 0/2 | - |
| resolve-cost-pure-read-only | 解析入口纯文件读取，subprocess.run 被 mock 抛出时仍正常工作（零 LLM/网络/测试成本） | pass | 0/2 | - |
| stale-modify-missing-hit | 陈日信号：modify 路径在主树 HEAD 不存在 → 命中陈日（is_stale_declaration=True） | pass | 0/2 | - |
| stale-modify-exists-false | modify 路径在主树 HEAD 存在 → 非陈日（is_stale_declaration=False） | pass | 0/2 | - |
| stale-new-kind-always-false | new kind 恒不误判陈日（基线期望不存在是正常语义） | pass | 0/2 | - |
| stale-delete-reference-excluded | delete/reference kinds 不进入陈日判定 | pass | 0/2 | - |
| relocate-credential-reject-no-new-path | 替代路径在实现分支 HEAD 不存在 → 凭据三要素不齐，MUST NOT 登记 | pass | 0/2 | - |
| relocate-credential-reject-no-source | 来源标注缺失 → 凭据三要素不齐，MUST NOT 登记 | pass | 0/2 | - |
| relocate-unique-basename-match | basename 在仓库内唯一命中 → match_basename_in_tree 返回候选列表 | pass | 0/2 | - |
| relocate-multiple-basename-no-auto | basename 多命中 → 不自动重定位，转终审或人工 | pass | 0/2 | - |
| relocate-rewrite-replaces-path | 三要素齐备时 relocate_declared_path 确定性替换旧路径为替代路径 | pass | 0/2 | - |
| credential-relocation-exempts | 重定位凭据在册 → _has_relocation_credential 返回 True，收缩豁免 | pass | 0/2 | - |
| credential-typo-verdict-exempts | typo 裁决审计记录在册 → _has_relocation_credential 返回 True（4.3 接入裁决） | pass | 0/2 | - |
| credential-no-record-false | 无凭据记录 → _has_relocation_credential 返回 False | pass | 0/2 | - |
| snapshot-returns-entries | snapshot_declaration_baseline 写入 declaration-baseline.json 含 path+kind 条目 | pass | 0/2 | - |
| shrinkage-entry-removed-violation | 基线条目在生效声明中被无声删除且无凭据 → violation: removed | pass | 0/2 | - |
| shrinkage-kind-rewritten-violation | 基线 modify 被改写为 reference（无裁决审计凭据）→ violation: removed | pass | 0/2 | - |
| shrinkage-credential-exempts | 重定位凭据在册 → 收缩豁免，violations 为空 | pass | 0/2 | - |
| shrinkage-no-baseline-conservative | 无基线快照 → 收缩防护降级保守，violations 为空（不误伤正常轮次） | pass | 0/2 | - |
| adjudication-stale-relocates | 陈日 modify 声明 → basename 唯一命中 → 机械重定位 → 守卫复检通过 → proceed | pass | 0/2 | - |
| dual-lane-fast-track-goes-to-judge | fast-track 缺件 → 进入终审流水线（置 blocked），MUST NOT 直按缺件重派 | pass | 0/2 | - |
| dual-lane-full-goes-to-judge | full 车道缺件 → 同一终审路径，行为一致 | pass | 0/2 | - |
| relocation-no-retry-budget | 陈日重定位走重定位通道 → proceed，_retry_count 保持 0，不消耗重派预算 | pass | 0/2 | - |
| new-test-files-delivered | 三份新增测试文件落盘存在：test_declaration_resolution.py / test_declaration_relocation.py / test_dual_lane_adjudication.py | pass | 0/2 | - |
| regression-resolution-suite | test_declaration_resolution.py 全量通过（9 passed），确认声明解析契约无回归 | pass | 0/2 | - |
| regression-relocation-suite | test_declaration_relocation.py 全量通过（18 passed），确认重定位协议无回归 | pass | 0/2 | - |
| regression-dual-lane-suite | test_dual_lane_adjudication.py 全量通过（3 passed），确认双车道统一无回归 | pass | 0/2 | - |
| full-suite-regression | 受影响存量测试文件零失败：test_deliverable_gate + test_tasksmd_relint_gate + test_delivery_declaration_premechanize + test_deliverable_declaration_triage | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 34 个（第 1 轮）。

- 首轮写入 34 个场景

