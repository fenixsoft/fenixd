# 验证报告：fix-run-cleanup-attach-spec-archive

> ⚠️ 本报告由框架于 2026-09-29T05:20:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-29T05:20:45.972197+00:00+run-result@mtime1790659245998625724

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.45M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| archive-cleans-top-and-archive-copies | SPEC 归档清理主路径：runs/ 顶层 impl-foo 产物与 runs/archive/ 归档副本 verify-foo 产物两处一并删除，返回清理计数 2，逐文件记 INFO 日志（spec specs/run-artifact-lifecycle/spec.md「归档 SPEC 后其产物两处均不存在」；签名出处 core/agent_runner/run_files.py:130 archive_spec_runs） | pass | 0/5 | - |
| archive-zero-impact-on-other-specs | 归档 SPEC foo 对 SPEC bar 的产物零影响：bar 的顶层与归档副本均保持原样，仅 foo 产物被清理（spec「归档对其他 SPEC 的产物零影响」；归属口径 run_spec_part 全等，core/agent_runner/run_files.py:105） | pass | 0/6 | - |
| archive-single-file-failure-not-blocking | 单文件删除失败不阻断归档主流程：归档副本中目录形态候选（unlink 必抛 OSError）触发单文件失败后，其余产物正常删除、流程不中断（spec「单文件删除失败不阻断」；fail-open 语义 core/agent_runner/run_files.py:177-179 既有口径） | pass | 0/4 | - |
| retention-terminal-run-moves-to-archive-unchanged | 清扫器第 1 步行为不变：终态 run 产物（末行 result）仍由 runs_retention_check 从活跃目录移入 archive/，活跃目录有界性保持（spec「活跃目录有界性不变」；签名出处 core/dashboard/data/runs.py:1069 runs_retention_check） | pass | 0/3 | - |
| retention-archived-artifact-of-active-spec-survives | 未归档 SPEC 的归档产物跨周期存活：archive/ 中活跃 SPEC foo 的产物（mtime 30 天、最旧）+55 个未超龄无主产物共 56 条（超过旧 keep=50），连续 3 个清扫周期后 foo 产物与全部无主产物均不被删除——锁定「归档目录不再按 runs.keep 上限删除」防旧逻辑复活（spec「未归档 SPEC 的归档产物跨周期存活」；旧 keep 消费点 runs.py:1092/1167-1169 应已拆除） | pass | 0/3 | - |
| retention-aged-unowned-artifact-deleted | 超龄无主产物兜底清理：archive/ 中 mtime 15 天前、归属不匹配任何活跃 SPEC 的 code-fix 车道产物被清扫器删除，且删除日志可查（含文件名）（spec「超龄无主产物被清理」；兜底常量 _LANE_RUN_RETENTION_DAYS=14，design D2） | pass | 0/3 | - |
| retention-young-unowned-artifact-kept | 未超龄无主产物保留：archive/ 中 mtime 距今 13 天（<14 天阈值）的无主 code-fix 产物不被清扫器删除（spec「未超龄无主产物保留」；14 天为模块常量非配置项，design Non-Goals） | pass | 0/2 | - |
| retention-aged-owned-artifact-kept-by-owner-guard | 活跃 SPEC 同名产物不受兜底影响：archive/ 中活跃 SPEC foo 的产物 mtime 30 天前仍保留（兜底只针对无主产物），同龄无主对照产物被删除——证明兜底逻辑确实执行且归属守卫生效（spec「活跃 SPEC 同名产物不受兜底影响」；活跃集=spec/changes/ 目录名集合，design D3） | pass | 0/3 | - |
| retention-fail-closed-on-active-set-scan-failure | 活跃 SPEC 集扫描失败时 fail-closed：注入 os.scandir/os.listdir 对 spec/changes 抛 OSError，清扫器不误删任何超龄无主产物、流程不崩溃（design Risks「误删活跃 SPEC 产物」防御；防御规格出处 spec/changes/fix-run-cleanup-attach-spec-archive/design.md:83-86） | pass | 0/3 | - |
| retention-stale-keep-config-inert-readside-removed | 残留配置无害 + 读侧拆除：config.yaml 残留 runs.keep=120 时清扫器正常执行（终态移入照常、keep 值不再保护超龄无主产物），且 runs.py 中 _resolve_runs_keep/_RETENTION_KEEP_DEFAULT 符号已不存在（spec「残留配置无害」+「读侧无任何消费点」；拆除点 core/dashboard/data/runs.py:1003/1013） | pass | 0/5 | - |
| config-admin-runs-managed-key-removed | config_admin 拆除 runs 受管键四处全集：_MANAGED_KEYS 无 runs、缺省展示（_default_echo_view）无 runs、写入分支忽略 runs 键不落盘（其余键 gates.approve_mode 正常落盘）、read_config/read_effective_config 回显均不含 runs 键（spec「配置 API 不再接受 runs 键」；拆除点 core/dashboard/data/config_admin.py:27/426/653-662/894-899/1039-1047） | pass | 0/8 | - |
| grep-no-stale-keep-residue | 全仓旧键残留清扫：代码面 core/tests/bin 中 _resolve_runs_keep/_RETENTION_KEEP_DEFAULT 符号零残留（tasks 5.1 测试替身旧键清理；spec/ 下 SPEC 文档与已归档历史报告提及符号属正常描述不在范围）、docs/help 全域 runs.keep 记载零残留（tasks 4.2；docs/help/11-logs.md:99/186 两处既有记载属清扫范围） | pass | 0/4 | - |
| api-config-post-ignores-runs-key | 配置管理 HTTP 契约：POST /api/config 提交含 runs 死键的补丁不再报错或 500，runs 键被忽略、其余受管键（gates.approve_mode=manual，与缺省同值零行为扰动）正常应用并读回确认（spec「配置 API 不再接受 runs 键」；路由出处 core/dashboard/routes/base.py:423 → settings_routes.py:92 _api_config_post → config_admin.write_config:1326） | pass | 0/5 | - |
| web-help-artifacts-doc-runs-section | 帮助中心呈现文件与数据地图文档：/help 页打开 10-artifacts.md，「.fenix/runs/ 运行记录」章节与 run 产物 jsonl 说明正常渲染、页面无控制台错误（docs/help/10-artifacts.md 交付物的 UI 呈现验收；出处 core/dashboard/static/src/app.tsx:135 /help 路由、core/dashboard/static/src/pages/help/index.tsx:32-45 hash query 读 doc 参数、docs/help/10-artifacts.md:123 章节标题） | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

