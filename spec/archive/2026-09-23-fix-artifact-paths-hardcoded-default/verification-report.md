# 验证报告：fix-artifact-paths-hardcoded-default

> ⚠️ 本报告由框架于 2026-09-18T19:41:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T19:41:40.035893+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 15.55M |
| 本链增量 Token（输出） | 0.25M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| declaration-tri-state-adjudication | 判定器三态判定表：has_build_artifacts 缺省/true/false × build_artifact_paths 空/非空 的判定与未裁决语义。跑 tests/test_artifact_paths_declaration.py::TestTriStateAdjudicationTable（真实输出行照抄自本机 pytest -v 运行）。spec 出处：specs/artifact-path-declaration/spec.md「has_build_artifacts 三态语义与裁决状态」Requirement；判定器实现 core/worktree_manager/artifact_paths.py:158-185。 | pass | 0/7 | - |
| declaration-no-default-symbols | 代码中不再存在内置默认前缀常量：DEFAULT_ARTIFACT_PREFIXES / _DEFAULT_STATIC_ROOT / _matches_default / _match_default / _is_build_artifact_path 被删除。改为精确验证：模块命名空间 hasattr 探查 + 全仓定义级检索（排除注释行），替换原 test_removed_default_symbols_no_longer_exist 用例（该用例全仓文本检索把测试文件自身与产品 docstring 迁移说明误判为残留，必然误报，见 judge 归因）。spec 出处：specs/artifact-path-declaration/spec.md「产物判定由配置驱动，无内置默认路径」Requirement Scenario「代码中不再存在内置默认前缀常量」；tasks.md 2.4。 | pass | 0/3 | - |
| declaration-dashboard-bestand-without-cfg | MODIFIED wip-artifact-scope 语义反转：未配置时 core/dashboard/static 产物不再被判真、显式配置后判真（框架自身仓库产物须经配置显式声明）。跑 TestDeclaredArtifactProject 族。spec 出处：specs/wip-artifact-scope/spec.md「产物前缀判定的默认作用域」Requirement Scenario「未配置时 dashboard 产物不再被判为真/显式配置后判真」；实现 core/worktree_manager/artifact_paths.py:247-260。 | pass | 0/5 | - |
| declaration-normalize-fail-safe | 配置规范化 fail-safe：非法形态（非列表/非字符串/绝对路径/.. 越界/前缀未以 / 结尾）丢弃并回退空集合，判定器构造不抛异常、判定不因非法值变宽。跑 TestNormalizeEmptyFallback 族。spec 出处：specs/wip-artifact-scope/spec.md「项目级产物前缀与通配配置」Requirement（非法项丢弃/配置形态非法时判定变空而非报错）；实现 core/worktree_manager/artifact_paths.py:40-92。 | pass | 0/4 | - |
| signal-gate-emits-and-skips | 运行期起草信号产生与抑制：未裁决（含主树干净无 WIP 重叠形态）时 _wip_overlap_gate 写 build_artifact_paths_missing；已裁决（false / 路径非空）不写。跑 tests/test_artifact_paths_signal.py 的写信号族。spec 出处：specs/artifact-path-autofill/spec.md「运行期未裁决时产生起草信号」Requirement（触发点 _wip_overlap_gate、早退前置、spec 字段 + evidence 项目名）；tasks.md 3.1-3.2。 | pass | 0/5 | - |
| signal-dedup-and-ingestion | 信号在途去重（同项目同类型未消费不重复写、跨项目不误去重）、admin_monitor 摄取解析 evidence 项目名并 mark_escalated 防重复唤起、store 写失败不抛穿闸门。跑 tests/test_artifact_paths_signal.py 的去重/摄取/写失败族。spec 出处：specs/artifact-path-autofill/spec.md「build_artifact_paths_missing 信号的摄取与唤起」Requirement；tasks.md 3.2-3.5。 | pass | 0/5 | - |
| detect-script-probe-candidates | 探测脚本 bin/fenix_detect_artifacts.py 对含 package.json build 脚本 + dist/ 目录的临时项目输出候选产物路径 JSON（has_build_artifacts=true、build_artifact_paths 含 dist/）。spec 出处：tasks.md 4.3 / 5.1 / 7.1（新增探测脚本 bin/fenix_detect_artifacts.py）；探测信息源实现 bin/fenix_detect_artifacts.py:50-147。 | pass | 0/5 | - |
| detect-script-write-idempotent | 探测脚本 --write 幂等性：已显式声明 has_build_artifacts 的项目跳过写入（不覆盖人工设置）；未裁决项目写入 worktree.has_build_artifacts + build_artifact_paths。spec 出处：tasks.md 5.2（幂等不覆盖）/ 7.2（回填入口幂等）；实现 bin/fenix_detect_artifacts.py:192-238。 | pass | 0/8 | - |
| web-verify-panel-user-scope-readonly | 验证页签产物路径卡片在用户级作用域下只读：显示项目级设置提示、不可编辑、三态只读展示。navigate #/settings（SPA hash 路由，出处 core/dashboard/static/src/app.tsx:111）+ 点菜单「验证」（core/dashboard/static/src/pages/settings/index.tsx:25）+ 断言卡片（core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288-323）。 | pass | 0/6 | - |
| web-verify-panel-project-tri-state | 项目级作用域：产物卡片渲染三态 Radio（未配置/有产物/无产物）+ 静态说明文案（判定完全由配置驱动）；选择「有产物」并添加 dist/ 路径后保存，配置回显路径列表。spec 出处：specs/artifact-path-dashboard-ui/spec.md「验证页签展示 has_build_artifacts 开关」（三态控件用 Radio.Group，VerifyPanel.tsx:239-243）；save 通路 VerifyPanel.tsx:62-92。 | pass | 0/7 | - |
| api-config-echo-tri-state-null | GET /api/config 回显 worktree.has_build_artifacts（未裁决时为 null 而非 false）与 worktree.build_artifact_paths，区分「未裁决」与「已声明无产物」。端点出处 core/dashboard/routes/base.py:270；回显通路 config_admin.py:460-464（worktree_config_view）→ artifact_paths.py:130-153。 | pass | 0/4 | - |
| api-config-reject-invalid-boolean | POST /api/config 提交 worktree.has_build_artifacts 为字符串「yes」→ 后端 400 拒绝且不写入。spec 出处：specs/artifact-path-dashboard-ui/spec.md「产物配置写入经后端校验」Scenario「非法布尔值被拒」；校验落点 config_admin.py:1046-1053。端点出处 core/dashboard/routes/base.py:287。 | pass | 0/2 | - |
| api-config-reject-invalid-path | POST /api/config 提交 build_artifact_paths 含未以 / 结尾的前缀「dist」→ 后端 400 拒绝并附合法形态提示。spec 出处：specs/artifact-path-dashboard-ui/spec.md「非法路径项被拒」Scenario；校验落点 config_admin.py:1036-1045（validate_build_artifact_paths）；端点出处 core/dashboard/routes/base.py:287。 | pass | 0/2 | - |
| web-verify-panel-declare-no-artifacts | 项目级作用域：切换到「无产物」并保存，路径列表隐藏、显示「已声明本项目无构建产物」结案提示（element_not_exist 验证列表隐藏）。spec 出处：specs/artifact-path-dashboard-ui/spec.md「关闭开关表示无产物」Scenario（false 态置灰/隐藏路径列表 + 结案提示）；实现 VerifyPanel.tsx:245-252、:94-95。 | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

