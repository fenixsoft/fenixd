# 验证报告：fix-verify-serving-disk-reclaim

> ⚠️ 本报告由框架于 2026-09-18T10:06:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T10:06:59.004987+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 11.44M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| reclaim-pytest-suite | serving_reclaim 全量单元测试（32 项）：覆盖判据矩阵（spec 存活/archiving 变更归档/无法解析/登记在册/活进程/宽限期）、回收执行（remove --force + prune、单条目失败继续、幂等、state 文件不触碰）、boot.log 回收（无主删除/存活保留/无法解析保留/在飞 run 保留）、返回结构（reclaimed/kept/boot_logs_reclaimed）、开关早退（禁用时零 git 调用）（covers: verify-serving-reclaim spec all scenarios；出处: tests/test_verify_serving_reclaim.py） | pass | 0/9 | - |
| deps-mode-default | resolve_deps_mode(None, None) 返回 hardlink（verify-deps-provision-default：无任何显式配置时走 hardlink）（出处: core/verify_contract.py:502-508） | pass | 0/2 | - |
| deps-explicit-overrides | 显式配置优先级：verify.yaml contract 的 deps_mode 优先于 config_value，两者均优先于代码默认（verify-deps-provision-default：显式配置覆盖默认）（出处: core/verify_contract.py:502-508, core/pm_engine/verification/serving_reclaim.py:26） | pass | 0/3 | - |
| config-template-defaults | .fenix/config.template.yaml verify 段显式列出 deps_mode: hardlink 与 serving_reclaim: enabled: true（verify-deps-provision-default：模板显式列出默认值）（出处: .fenix/config.template.yaml:238-244） | pass | 0/4 | - |
| config-write-sr-persist | config_admin 写入 verify.serving_reclaim.enabled=false → 读回确认持久化，且 _SYNC_PAGE_KEYS["verify"] 覆盖 serving_reclaim 子键（verify-serving-reclaim：开关经 Dashboard 持久化，保存路径 MUST 纳入验证页受管键集合）（出处: core/dashboard/data/config_admin.py:79,1417） | pass | 0/6 | - |
| config-write-validation | config_admin 校验：serving_reclaim.enabled 非布尔值被 400 拒绝且不落盘（verify-serving-reclaim：关闭时清扫早退的场景配置侧拒非法值）（出处: core/dashboard/data/config_admin.py:925-927） | pass | 0/4 | - |
| config-admin-merge | config_admin merge 分支：先写 static_scope=worktree 再写 serving_reclaim.enabled=false → 两键共存，merge 不覆盖既有键（verify-serving-reclaim：开关与其它 verify.* 键共存；核心/dashboard/data/config_admin.py:722-736） | pass | 0/5 | - |
| dashboard-data-roundtrip | test_verify_config_roundtrip_and_validation 单元测试通过（覆盖 verify.* 受管键读写回环、缺省回显含 serving_reclaim、非法值拒绝不落盘）（verify-deps-provision-default+Dashboard 一致面）（出处: tests/test_dashboard_data.py:51） | pass | 0/3 | - |
| api-defaults-read | GET /api/config（用户级）读回 verify 段默认值：deps_mode=hardlink、serving_reclaim.enabled=true（verify-deps-provision-default：默认模式配置与界面一致；verify-serving-reclaim：开关缺省为开）（出处: core/dashboard/routes/settings_routes.py:41） | pass | 0/4 | - |
| verify-panel-default-state | Dashboard 验证契约页默认状态：hardlink 选项选中且标注含「默认」，serving_reclaim 开关默认开启（verify-deps-provision-default：界面缺省选中 hardlink 且该项标注含「默认」；verify-serving-reclaim：Dashboard 提供开关且缺省为开）（出处: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:36-39,138-148,151-162） | pass | 0/6 | - |
| deps-fallback-no-node-modules | 主树无 node_modules 时 hardlink 模式自动降级 prefer-offline（npm ci），MUST NOT 失败（verify-deps-provision-default Spec scenario: 主树无 node_modules 时降级 prefer-offline）（出处: tests/test_verify_contract.py:242） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

