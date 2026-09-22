# 验证报告：evo-merge-back-wip-artifact-scope

> ⚠️ 本报告由框架于 2026-09-18T07:29:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T07:29:10.799233+00:00

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 14.52M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-artifact-scope-suite | 产物判定器与 WIP 重叠闸门全量单元测试（tests/test_worktree_wip_artifact_scope.py，28 用例）：D5-1 判定矩阵（默认前缀命中/根级 dist 默认假/配置 dist/ 后真/通配不跨目录/非法项丢弃/非法形态回退默认）、D5-2 WIP 重叠闸门（产物不计入重叠/语义仍计入/spec-changes 排除不受影响）、D5-3 预演闸分类（全产物放行/含语义 rehearsed）、D5-4 链路切断（纯产物重叠对齐 HEAD 且 last_stash_pop_conflicts 为空/主树独有产物不丢弃/对齐失败回退）、D5-5 故障回退与逐字节兼容。被测产物：core/worktree_manager/artifact_paths.py + mergeback.py + dist_conflicts.py 实例判定器消费点（tests/test_worktree_wip_artifact_scope.py:1-520）。covers: ["artifact-matcher", "wip-overlap-gate", "d3b-chain-break"]。 | pass | 0/11 | - |
| cli-stray-identical-regression | 既有 stray/identical 自愈语义零回归（tests/test_worktree_stray_and_identical.py，11 用例）：判定器改造不改变 _heal_unmerged_files / _drop_superseded_stash_entry 语义（spec Non-Goals），既有断言必须全绿（D5-5 兼容性验收）。被测产物：core/worktree_manager/ 包级默认语义别名 _is_build_artifact_path 委托实例判定器后行为逐字节不变（core/worktree_manager/__init__.py:63-79、tests/test_worktree_stray_and_identical.py:81-273）。 | pass | 0/4 | - |
| cli-config-template-check | 配置模板补默认值段：.fenix/config.template.yaml 含 worktree.build_artifact_paths 注释说明与合法形态示例（目录前缀以 / 结尾、通配含 *），未配置时等价默认集合的说明齐全（.fenix/config.template.yaml:199-211）。被测产物：.fenix/config.template.yaml。 | pass | 0/5 | - |
| cli-injection-points-check | 配置注入与消费点齐备：fenixd.py 解析 worktree.build_artifact_paths 传入 WorktreeManager 构造（fenixd.py:246/255-256）；lifecycle.py 新增 build_artifact_paths 构造参数并经 normalize_artifact_patterns 构造 ArtifactPathMatcher（core/worktree_manager/lifecycle.py:42/110）；mergeback.py 消费实例判定器（_wip_overlap_gate 产物切分 mergeback.py:159-160、预演闸 non_artifact mergeback.py:382、冲突分类 mergeback.py:618-621）；config_admin.py 受管键/来源标注/写校验落点（core/dashboard/data/config_admin.py:98/221-222/319/519/814-816/992-1003）。被测产物：fenixd.py + core/worktree_manager/lifecycle.py + core/worktree_manager/mergeback.py + core/dashboard/data/config_admin.py。 | pass | 0/5 | - |
| api-config-worktree-read | 配置读侧回显 worktree.build_artifact_paths（D6）：GET /api/config 响应含 worktree.build_artifact_paths 数组（未配置时为空列表，来源标注 worktree.build_artifact_paths 不在写白名单 = 只读键）。路由出处 core/dashboard/routes/base.py:252（_API_GET_ROUTES），处理链 _get_config → _api_config_get → read_effective_config/read_config → worktree_config_view（core/dashboard/data/config_admin.py:443-447/634-637）。 | pass | 0/3 | - |
| api-config-artifact-paths-invalid-rejected | 写入侧前置校验拒绝非法 build_artifact_paths（D6）：POST /api/config 携带非列表/非字符串/未以 / 结尾前缀/绝对路径等非法项 → 400 明确错误（拒绝而非静默丢弃，误配会静默丢弃语义改动属高风险），回读确认未被写入。路由出处 core/dashboard/routes/base.py:268（_API_POST_ROUTES），校验链 _post_config → _api_config_post → write_config 前置校验（core/dashboard/data/config_admin.py:992-1003）。 | pass | 0/4 | - |
| web-verify-panel-artifact-paths | Dashboard 验证契约页「构建产物路径」只读展示（D6）：设置页「验证」页签渲染卡片（标题「构建产物路径」）+ 说明文案（worktree.build_artifact_paths 语义与推荐值形态）+ 未配置时显示「未配置（使用框架默认判定集合）」空态（本仓库主树未配置该键）。SPA 路由 #/settings（core/dashboard/static/src/app.tsx:111），设置页菜单项 key='verify' label='验证'（core/dashboard/static/src/pages/settings/index.tsx:31），VerifyPanel 卡片渲染（core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:124-143）。covers: ["verify-panel-artifact-card"], declared_display: ["quick-links-standalone-sync", "quick-links"]（均为 proposal 引用的历史告警记录中的 spec 名，非本页交互元素）。 | pass | 0/6 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

