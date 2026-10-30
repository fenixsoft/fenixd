# 验证报告：evo-distill-model-name-fallback

> ⚠️ 本报告由框架于 2026-10-30T12:04:04Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T12:04:03.424125+00:00+run-result@mtime1793361843523832171

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.13M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| distill-model-config-fallback-warn | R1 配置面：knowledge.model 读取器契约——缺省未配置回退不传名并 WARNING、空串/非字符串非法值回退不传名并告警（非法值不流入 spawn 参数）、合法值 strip 后生效。出处 core/config.py:3625-3666（get_knowledge_model，回退必告警哲学）。 | pass | 0/4 | - |
| distill-spawn-model-passthrough | R1 spawn 透传：蒸馏 run 恒传显式裸模型名——配置 knowledge.model 生效时模型名经 SpawnRequest.model→claude_adapter --model 透传进 spawn argv（隔离宿主 ANTHROPIC_DEFAULT_*_MODEL 别名毒化）；缺省回退现行为不传 --model。出处 core/knowledge.py:1699（_spawn_model_from_config）与 :1766-1769（SpawnRequest.model 注入）。 | pass | 0/3 | - |
| distill-alias-reject-bare-retry-success | R2 正向路径：未显式传名时非零退出且 stderr 命中 [claude-code:unrecognized_model] 别名形态（glm-5.3-flash[1M]），派生裸模型名单次重试并成功——spawn 恰 2 次（首次无名、第二次裸名）、重试成功按正常完成入账、不登重试台账。出处 core/knowledge.py:1703-1729（拒识判别与裸名重试分支）。 | pass | 0/2 | - |
| distill-retry-fail-todo-once | R2 异常路径：裸模型名重试仍被拒→走既有 give_up→清理半成品→登重试台账，todo.md 台账恰一条、reason 注明拒识形态 unrecognized_model、生效模型名与「已自动重试一次仍失败」，不重复登记。出处 core/knowledge.py:1730-1733（重试失败收场）。 | pass | 0/2 | - |
| distill-explicit-reject-no-retry | R2 收窄分支：显式传 knowledge.model 名仍被拒属网关侧确定性拒识（同一模型名再试必然再拒），MUST NOT 同因重试——spawn 恰 1 次，直接 give_up→登台账且 reason 注明生效模型名与「不重试」。出处 core/knowledge.py:1708-1715（显式传名仍被拒终态收场）。 | pass | 0/2 | - |
| distill-bare-reject-no-retry | R2 裸名形态分支（MERGE-NOTES 2026-10-30 裸名拒识先例）：未传名但生效名已是无别名后缀的裸名（glm-5.3-flash 仍被拒）——无可剥后缀派生兜底名，同因重试必然再拒，不重试直接收场，台账注明生效模型名。出处 core/knowledge.py:760-765（_bare_model_name）与 :1734-1739（无可剥后缀终态收场）。 | pass | 0/2 | - |
| distill-stale-alert-idempotent | R3 正向+幂等：todo.md 重试行日期节登记超 24h 未重试→恰一条 kind=signal、signal_type=knowledge_distill_retry_stale 的 admin 提醒（.fenix/admin_alerts.json）且 stale 名单含归档名；同日再扫描以 daemon 进程内当日标记幂等跳过（suppressed=true）不重发。出处 core/knowledge.py:827-901（check_retry_ledger_age）与 :773（RETRY_STALE_AFTER=24h）。 | pass | 0/2 | - |
| distill-stale-scan-no-new-failures | R3 周期性反「顺带扫描」：无任何蒸馏派发、无新失败发生时直接调用扫描仍产生欠账提醒——蒸馏车道长期无新失败时提醒照常产生（恰为本 SPEC 主张实例的场景）。出处 core/knowledge.py:774-777（周期扫描不依赖新失败口径）。 | pass | 0/2 | - |
| distill-stale-stop-checked-removed-fresh | R3 停止条件与空状态：重试行被勾选 [x] 后停止提醒；文件无欠账行（行已移除）与行仅在当日日期节（登记未超 24h）时不产生提醒——空台账静默不刷屏。出处 core/knowledge.py:796-824（_stale_distill_retry_lines 只收未勾选行）。 | pass | 0/3 | - |
| distill-stale-daemon-mount-static | R3 挂载面静态取证：蒸馏重试台账龄期扫描挂 daemon 主循环 300s 检查点（check_retry_ledger_age(PROJECT_ROOT)）且 dashboard 路由零接入（core/dashboard/ 无引用）——对齐「挂 daemon 既有周期维护循环；dashboard --serve 不接入」契约。出处 fenixd.py:1198-1205（300s 检查点挂载）。 | pass | 0/3 | - |
| distill-fallback-regression-full-file | 回归点：tests/test_knowledge_distill_resume.py 全文件 30 用例全数通过——R1/R2/R3 落地不回归既有蒸馏台账生命周期（give_up→清理→登记、recover_pending、idle 维度）行为。出处 tests/test_knowledge_distill_resume.py:186-491（既有类）与 :492-721（本 SPEC 新增 4 类，实测 30 passed）。 | pass | 0/6 | - |
