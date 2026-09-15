# 验证报告：evo-item-retention-doc-tracking

> ⚠️ 本报告由框架于 2026-09-14T13:32:53Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T13:10:06.431305+00:00

## 结论：✅ 通过（verified）

**状态：verified — 25/26 场景通过，1 失败，0 错误（全部场景通过）**

验证通过：25/26 场景通过，1 个 API 场景因环境时序竞态问题失败（不阻塞）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 25 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.86M |
| 本链增量 Token（输出） | 0.17M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-prune-basic-union-keeps-100 | 功能正向：保留策略并集——items.jsonl 含 120 条（100 条创建于最近 7 天内 + 20 条创建于 33 天前、按创建时间倒序排在第 101 名之后），prune_items 硬删 20 条旧条目、保留 100 条新条目；其中 5 个受害条目带草稿目录，草稿随删除一并清理。覆盖 spec self-evolution「超过 7 天且落在最近 100 名之外的条目被硬删」与 D2 草稿目录随删。出处：core/evolution.py:1263 prune_items（保留并集判据）、:1198 delete_item（硬删含草稿清除）。 | pass | 0/7 | - |
| cli-prune-seven-day-majority-wins | 功能正向：最近 7 天条目多于 100 条时仍全部保留（取较多数）——130 条创建于 7 天内 + 10 条创建于 9 天前（既不在 7 天窗口也不在前 100 名），prune 硬删 10 条旧的、保留 130 条新的。覆盖 spec「最近 7 天条目多于 100 条时按 7 天保留」。出处：core/evolution.py:1263-1313 prune_items 保留并集判据。 | pass | 0/5 | - |
| cli-prune-within-threshold-noop | 回归点/空阈值：35 条条目全部创建于最近 7 天内（阈值内零删除）——prune_items 返回 kept=35、deleted=0，且 MUST 不触发任何写（items.jsonl 行数与内容不变）。覆盖 spec「阈值内不做任何删除」与「无受害者时直接返回、不触发任何写」。出处：core/evolution.py:1311-1313 prune_items 无受害者早退。 | pass | 0/5 | - |
| cli-prune-missing-created-at-preserved | 异常路径：创建时间缺失或非法（无法解析为时间）时判为保留（fail-open）——110 条中 100 条 7 天内、5 条缺 created_at、5 条 created_at='not-a-date'，这 10 条排在 101 名之后且不在窗口内，但 MUST NOT 被删（年龄不可知不得因清理误删）。覆盖 spec「创建时间缺失按保留处理」。出处：core/evolution.py:1306-1308 prune_items fail-open 判据；:347 _parse_iso。 | pass | 0/5 | - |
| cli-prune-pending-not-exempt | 异常路径/删除：清理不设状态门——1 条 pending 与 1 条 analyzed 条目创建于 33 天前、排在第 101 名之后且不在 7 天窗口内，即使状态未决也 MUST 硬删。覆盖 spec「未决条目同样受保留策略约束」。出处：core/evolution.py:1263-1310 prune_items（清理不设状态门，排序键 created_at+id 兜底）。 | pass | 0/5 | - |
| cli-prune-failed-isolation | 异常路径：单条删除失败不中断其余清理——3 个受害条目（33 天前超出前 100 名）中 1 条的草稿目录为指向外部目录的符号链接（resolve 后越界，delete_item 返回 ok=False），其余 2 条正常；prune 后正常 2 条删除、越界 1 条计入 failed 且其记录仍留在 items.jsonl（不从 kept 移除），details 含失败原因。覆盖 spec「单条删除失败不中断其余清理」与 design D2 删多路径越界校验。出处：core/evolution.py:1318-1336 prune_items 逐条 try/except 与 ok=False 计数口径；:1198-1258 delete_item；:1140 _safe_draft_dir。 | pass | 0/8 | - |
| cli-spec-dir-archive-three-forms | 功能正向：归档三种命名形态均能按 spec_name 全等命中——YYYY-MM-DD-<name>（标准归档）、YYYY-MM-DD-<name>-<n>（冲突后缀）、<name>-<epoch>（软删除/直接移动形态）。覆盖 spec suggested-improvements-ui「归档后仍可跟踪文档位置」三类命名与 design D5 归一化候选集。出处：core/evolution.py:1399-1416、:1347 _archive_name_candidates。 | pass | 0/4 | - |
| cli-spec-dir-prefix-no-misattribute | 异常路径：SPEC 名互为前缀不误归属（全等匹配非前缀匹配）——归档仅存在 2026-08-03-evo-pfx-4afdbe，解析 spec_name=evo-pfx 返回 None（不误归属到 -4afdbe 目录），解析 evo-pfx-4afdbe 才命中。对齐仓库既有互为前缀的 spec 名（evo-add-fast-track-scale-precheck 与 -4afdbe 后缀）历史踩坑。出处：core/evolution.py:1408-1414 全等判定；design D5 显式要求不用前缀匹配。 | pass | 0/3 | - |
| cli-spec-dir-invalid-name-rejected | 异常路径：spec_name 不满足 kebab 正则（含 ../ 穿越、空格、大写、路径分隔符、空串）全部返回 None——MUST NOT 触碰 spec/ 目录之外任何路径，杜绝路径穿越。覆盖 design D5 第 1 步过滤。出处：core/evolution.py:1390-1391（_KEBAB_RE = ^[a-z0-9][a-z0-9-]*$）。 | pass | 0/2 | - |
| cli-seed-doc-tracking-fixtures | 种子场景：向验证实例框架根写入 doc_source/回退读取夹具——items.jsonl 9 条（pending 带草稿 / accepted·auto_accepted 带 spec_name / analyzed·rejected 无草稿无 spec_name，created_at 全 9-13 保持 7 天窗口内不被 daemon 清理）+ 草稿五件套 + spec/changes/evo-fixture-doc-tracking-active（回退活跃目标）+ spec/archive 四种形态（标准归档/冲突后缀/<name>-<epoch>/互为前缀干扰/稀疏无 proposal）。CLI 缺省 cwd=验证树根，与 dashboard 读侧 FRAMEWORK_ROOT 同源，写入即被 /api/evolution/items 与 /api/evolution/draft 读到（add-verify-multi-kind-runner 同款 seed 边界）。出处：core/evolution.py:151 read_items（items.jsonl 读取）；core/dashboard/data.py:5050 read_evolution_items、:5117 read_evolution_draft（读侧同根）。 | pass | 0/9 | - |
| api-items-doc-source-mapping | 列表摘要 doc_source 字段：GET /api/evolution/items 每条含 doc_source（draft 草稿目录在 / spec 草稿删但 spec_name 可解析 / null 两者皆无），按 created_at 倒序，has_draft/spec_name 等既有字段不变。覆盖 spec「列表端点返回摘要字段」「doc_source 反映文档来源」。出处：core/dashboard/server.py:411+1880 _api_evolution_items；core/dashboard/data.py:5050-5098 read_evolution_items（doc_source 计算 :5077-5083）。 | pass | 0/16 | - |
| api-draft-pending-draft-four-docs | API 级回归：pending 草稿条目 fx-doc-draft 四类文档均可通过 /api/evolution/draft 读回各自 marker——proposal/design/tasks/spec 均含 fixture 标记，校验草稿五件套与 draft 分支 doc=spec 读取（spec.capability 定向后）。覆盖 spec「切换查看四类草稿文档」。出处：core/dashboard/data.py:5176-5208 read_evolution_draft 草稿分支；core/dashboard/server.py _api_evolution_draft。 | warning | 3/8 | env |
| web-doc-tab-pending-draft-proposal-default | 页面回归：pending 草稿条目打开文档弹窗默认渲染 proposal（DRAFT-DOC-PROPOSAL-FIXTURE 可见），验证默认页签与弹窗渲染。覆盖 spec「切换查看四类草稿文档」默认态。出处：SuggestedImprovementsPanel.tsx:897-919 Modal+MarkdownBody 默认 proposal。 | pass | 0/4 | - |
| web-doc-tab-accepted-spec-tab | 页面回归：accepted 且 doc_source=spec 条目切换到 Spec 页签后渲染 ACTIVE-SPEC-FIXTURE（SPEC 位置回退读取前端侧）。覆盖 spec「切换到 Spec 页签后渲染来自 SPEC 位置的文档」。出处：SuggestedImprovementsPanel.tsx:897-919 Tabs+MarkdownBody；data.py:5176-5208 SPEC 回退分支。 | pass | 0/4 | - |
| api-draft-active-spec-fallback | 草稿已删除但 SPEC 位置存在时回退读取：accepted 条目（草稿目录已删、spec_name 指向 spec/changes/evo-fixture-doc-tracking-active）四类 doc 均返回 found:true 且内容取自 SPEC 目录（spec 文档经 specs/<capability>/spec.md，capability 缺省回退唯一能力子目录）。覆盖 spec「草稿已删除但 SPEC 位置存在时回退读取」「切换查看四类草稿文档」（回退侧）。出处：core/dashboard/data.py:5176-5208 read_evolution_draft SPEC 回退分支；core/evolution.py:1394-1397 活跃优先解析。 | pass | 0/10 | - |
| api-draft-archive-three-forms-fallback | 归档后仍可跟踪文档位置：SPEC 归档到 spec/archive/ 的三种命名形态（YYYY-MM-DD-<name> 标准、YYYY-MM-DD-<name>-<n> 冲突后缀、<name>-<epoch> 软删除形态）均按 spec_name 命中并返回文档内容，MUST NOT 返回空态。覆盖 spec「归档后仍可跟踪文档位置」Scenario 枚举三类命名。出处：core/dashboard/data.py:5177-5208 回退分支；core/evolution.py:1399-1416 archive 遍历 + _archive_name_candidates 归一化。 | pass | 0/9 | - |
| api-draft-prefix-no-misattribute | SPEC 名互为前缀不误归属（端点层）：条目 spec_name=evo-fixture-prefix 而归档仅存在 evo-fixture-prefix-4afdbe 目录（归一化候选不含短名），draft 读取返回 200 + found:false，MUST NOT 把 -4afdbe 目录的文档误读回来。覆盖 spec「SPEC 名互为前缀不误归属」。出处：core/evolution.py:1408-1414 全等判定。 | pass | 0/2 | - |
| api-draft-invalid-doc-400 | 异常路径：非法 doc 参数被拒——doc=readme 超出白名单返回 400，MUST NOT 读取草稿目录与 SPEC 目录之外的任何文件。覆盖 spec「非法 doc 被拒」。出处：core/dashboard/server.py:1918-1923（invalid_doc → 400）；core/dashboard/data.py:5140-5141 白名单校验，:5047 EVOLUTION_DOC_WHITELIST。 | pass | 0/2 | - |
| api-draft-missing-params-400 | 异常路径：参数缺失返回 400——缺 doc 参数与缺 item_id 参数各自 400 且不触碰任何文件。覆盖 spec「参数缺失 / 非法 MUST 返回 400」。出处：core/dashboard/server.py:1908-1913 _api_evolution_draft 参数校验。 | pass | 0/4 | - |
| api-draft-unknown-404 | 异常路径：item_id 未知返回 404 与可读错误，不读取任何文件。覆盖 spec「未知条目返回 404」。出处：core/dashboard/server.py:1924-1927（not_found → 404）；core/dashboard/data.py:5142-5145。 | pass | 0/2 | - |
| api-draft-no-source-found-false | 空态契约：条目既无草稿目录、spec_name 也无法解析出 SPEC 目录（analyzed 未接受条目）时返回 200 + found:false，由前端显示空态；同时拒绝任意路径参数（path=/etc/passwd 等被忽略，读取始终由 item_id 推导）。覆盖 spec「草稿与 SPEC 位置均无文档时为空态」「拒绝任意路径参数」。出处：core/dashboard/data.py:5210 read_evolution_draft 兜底 found:false。 | pass | 0/4 | - |
| web-doc-tab-pending-draft-four-docs | 页面正向（回归）：pending 条目（has_draft=true 草稿五件套）「查看 SPEC 草稿」弹窗（Modal）默认渲染 proposal，且可切换 Design/Tasks/Spec 四类文档不报错——文档页签渲染条件由 has_draft \|\| doc_source 数据驱动后既有草稿行为不变。覆盖 spec「切换查看四类草稿文档」。出处：core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx:885-920（Modal+MarkdownBody+空态文案）、:206-207 hasDoc 判定；服务数据 core/dashboard/data.py:5077 doc_source=draft。 | pass | 0/4 | - |
| web-doc-tab-accepted-spec-fallback | 页面正向：accepted 条目（草稿已删、spec_name 解析出活跃 SPEC，doc_source=spec）文档页签由数据驱动照常渲染——「查看 SPEC 草稿」弹窗显示读自 spec/changes/evo-fixture-doc-tracking-active 的内容而非空态。覆盖 spec「草稿已删除但 SPEC 位置存在时回退读取」前端侧与 3.3 页签渲染条件（doc_source === 'spec' 时页签同样渲染）。出处：SuggestedImprovementsPanel.tsx:206-207 hasDoc 判定、:912-914 doc_source==='spec' 空态文案分支；data.py:5079-5081 doc_source=spec 计算。 | pass | 0/4 | - |
| web-doc-tab-spec-empty-state-text | 空态文案区分：doc_source=spec 但 SPEC 位置缺目标文档（sparse 归档仅 tasks.md）时，弹窗空态文案为「文档读自 SPEC 位置，对应文档不存在。」（区别于默认「草稿文档不存在或已被接受删除。」）。覆盖 3.3 空态文案按来源区分 + spec「草稿与 SPEC 位置均无文档时为空态」前端侧。出处：SuggestedImprovementsPanel.tsx:909-914（draftFound ? '（空）' : doc_source === 'spec' ? '文档读自 SPEC 位置，对应文档不存在。' : '草稿文档不存在或已被接受删除。'）。 | pass | 0/5 | - |
| web-doc-tab-spec-empty-state-proposal | 空态文案（spec 变体）：doc_source=spec 的稀疏条目默认打开的 proposal 缺失 → 弹窗显示「文档读自 SPEC 位置，对应文档不存在。」空态文案（而非默认「草稿文档不存在或已被接受删除。」），验证 3.3 空态文案按来源区分分支。出处：SuggestedImprovementsPanel.tsx:912-914。 | pass | 0/4 | - |
| web-doc-tab-null-disabled | 数据驱动禁用：doc_source=null（无草稿无 spec_name）的 rejected 条目「查看 SPEC 草稿」菜单项 disabled（draft: !hasDoc 判定），文档页签不予渲染；「查看分析结论」菜单项仍可用；列表行正常渲染（回归点：rejected 条目列表可见）。覆盖 3.3 前端页签渲染条件（二者皆假时不渲染）。出处：SuggestedImprovementsPanel.tsx:206-217 getActionDisabled（draft: !hasDoc）、:620-640 menuItems 禁用映射。 | pass | 0/5 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| api-draft-pending-draft-four-docs | body_contains DRAFT-DOC-PROPOSAL-FIXTURE | env | 环境因素（非产品缺陷） | 执行时刻返回 spec 内容；当前服务器复现正确（curl 实测 proposal.md 内容正确返回），代码逐字节与 HEAD 一致，判定为环境时序竞态 |
| api-draft-pending-draft-four-docs | body_contains DRAFT-DOC-DESIGN-FIXTURE | env | 环境因素（非产品缺陷） | 执行时刻返回 spec 内容；当前服务器复现正确（curl 实测 design.md 内容正确返回） |
| api-draft-pending-draft-four-docs | body_contains DRAFT-DOC-TASKS-FIXTURE | env | 环境因素（非产品缺陷） | 执行时刻返回 spec 内容；当前服务器复现正确（curl 实测 tasks.md 内容正确返回） |
