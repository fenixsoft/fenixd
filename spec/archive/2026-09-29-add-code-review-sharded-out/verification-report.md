# 验证报告：add-code-review-sharded-out

> ⚠️ 本报告由框架于 2026-09-23T19:18:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-23T19:18:36.860932+00:00

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.58M |
| 本链增量 Token（输出） | 0.16M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-shard-paths-glob-numeric-order-boundary | shard_paths 分片发现：glob out-<run_id>-b*.jsonl、按批次 N 数值升序（b10 排 b2 后，非字典序）、run_id 边界隔离（他 run 分片不串入）、无分片返回空表。出处：spec code-review-agent D1（tasks 1.1）；core/code_review.py:51（out_path 同目录约定） | pass | 0/3 | - |
| cli-progress-aggregate-dedupe-invalid-lines | 聚合读侧去重与无效行：分片 17+9 行 + 主产物含 2 个重复 file 行与 2 个新 file 行 + 空行/不可解析行/非 dict 行/findings 缺失行，read_progress.done 按去重后有效 file 数计=28，current 取 mtime 最晚来源末行 file；无效行不计数、不使读取失败。出处：tasks 1.1/1.2（design D2 去重口径）；core/code_review.py:662（read_progress 现状） | pass | 0/3 | - |
| cli-progress-shards-realtime-no-main | 分片进度实时可见（SPEC 场景原文）：run running，主产物不存在，分片 b1 有 17 行、b2 有 9 行有效行 → read_progress 返回 done=26、total=30（manifest 长度）、running=true、current=b2 末行 file；再删除分片后主产物缺位口径一致性由下游 api/web 场景复用同一夹具（落 scheduling-showcase）。出处：spec code-review-progress-visibility Scenario 分片进度实时可见/主产物缺失不归零；tasks 1.2 | pass | 0/4 | - |
| cli-progress-legacy-main-only-and-empty | 迁移不变量回归：旧 run 纯主产物在新聚合口径下行为不变（仅主产物 26 有效行+2 垃圾行 → done=26、current 取主产物末行）；空项目（无任何 code-review run）返回 base 形态且响应键集恰为 6 键（running/review_id/review_kind/total/done/current）。出处：design Migration Plan（分片空集退化为单文件读取）；tasks 1.2/5.2（形状不变） | pass | 0/4 | - |
| cli-stall-detect-threshold-matrix | check_progress_stall 判定矩阵：running+聚合 0 行+16 分钟 → 返回 {run_id, minutes}；有分片行（done=26）→ None；run 终态（result 收尾行）→ None；14 分钟（<缺省 15）→ None；阈值 stall_alert_minutes=-5/非整数/缺省 → 与 15 一致（14 否 16 是）；阈值=30 时 16 分钟否 31 分钟是（证明配置键真实生效）；无任何 run → None。出处：spec code-review-progress-visibility Requirement 事中零进度停滞告警 3 场景；tasks 1.3；core/admin_monitor.py:833（周期节拍调用方） | pass | 0/6 | - |
| cli-stall-alert-monitor-wiring-dedup | 停滞告警接入周期节拍：AdminMonitor.run_once 对 running+零进度+超阈值的夹具项目产生一条含去重键 code-review-stall-<run_id> 与 run_id 的 admin 告警记录（AdminStore 落盘），再次 run_once 告警条数不变（单 run 至多一条）；对照项目（有分片行 done=26）不产生告警。出处：spec D4；tasks 3.1；tests/test_admin.py:83 make_monitor 同款 harness 形态 | pass | 0/4 | - |
| cli-gate-aggregate-existence | 产物硬门聚合口径：仅分片存在且含有效行 → 放行（返回 None）；主产物与分片全缺失 → 判失败且 error 文案含「零有效行」并点名 run_id；主产物有≥1 有效行 → 放行（旧口径不回归）；主产物仅垃圾行 → 判失败。经 inspect 按形参名自适应调用 _check_repo_code_review_artifact（D5 允许两种签名形态）。出处：spec code-review-agent Requirement 产物硬门聚合口径 2 场景；tasks 2.2；core/agent_runner/result_gate.py:813（现状单文件口径） | pass | 0/6 | - |
| cli-ingest-aggregate-dedupe | 收尾 ingest 聚合读侧：分片 b1/b2 + 主产物的 findings 合并落账口径——跨来源文件齐全、重复 file 行按先落盘（分片优先）保留一条、坏字节分片跳过不中断（仍返回 list）。经 inspect 按形参名自适应调用 _read_code_review_out。出处：spec code-review-agent Scenario 主产物与分片重复行去重；tasks 2.1；core/agent_runner/maintenance_runs.py:1106（现状单文件读侧） | pass | 0/4 | - |
| cli-prompt-shard-and-no-wait-clauses | 提示词契约：agents/code-review.md 含分片直写路径模板 out-<run_id>-b（或 {run_id} 形态）、子代理审完立即落分片义务、禁 async 等待收工条款（launched 元数据 + MUST NOT…等待 同句、轮询推进、非交互模式机制原因）、主 agent 不重写分片已落盘批次。出处：spec D3；tasks 4.1/4.2；agents/code-review.md:64-68（现行落盘纪律段） | pass | 0/3 | - |
| cli-config-template-and-whitelist | 配置契约：.fenix/config.template.yaml 的 admin.code_review 注释段新增 stall_alert_minutes 说明（含缺省 15 语义）；core/dashboard/data/config_admin.py 键白名单/回显放行 stall_alert_minutes 子键。出处：tasks 3.2；spec code-review-progress-visibility（阈值 MUST 经该配置键）；core/dashboard/data/config_admin.py:75-77（既有 admin.code_review 白名单条目） | pass | 0/3 | - |
| cli-regression-suite-green | 回归点：tests/test_code_review.py 全绿（含实现者本 SPEC 新增的 5.1-5.4 用例：shard_paths/聚合读取/read_progress 聚合/硬门聚合/check_progress_stall）。只断言套件 exit 0 与 passed 汇总，不臆造具体用例名。出处：tasks 5.1-5.4；tests/test_code_review.py（现 61 用例基线全绿） | pass | 0/2 | - |
| api-progress-shape-contract | 进度端点响应形状契约（回归）：GET /api/code-review/progress?project=scheduling-showcase 返回 200 且响应恰含 running/review_id/review_kind/total/done/current 六键、类型正确（形状 MUST NOT 变化；取值随状态不assert）。出处：core/dashboard/routes/base.py:338、core/dashboard/routes/code_review_routes.py:66-75；spec（响应字段形状 MUST NOT 变化） | pass | 0/2 | - |
| api-config-stall-minutes-write-read | 阈值配置写链：POST /api/config?project=scheduling-showcase 写 code_review.stall_alert_minutes=20（200 + 回读生效），GET /api/config?project=scheduling-showcase 复读 code_review.stall_alert_minutes=20（键白名单放行 + 受管段写链 + 缺省回显链路）。出处：tasks 3.2/3.3；core/dashboard/routes/settings_routes.py:69-114（config POST 写路径）；admin.code_review 受管段约定 config_admin.py:75-76 | pass | 0/4 | - |
| web-settings-quality-stall-input | 设置页阈值输入项在场且可交互：导航 http://127.0.0.1:8787/#/settings（出处 core/dashboard/routes/base.py:565 GET /、core/dashboard/static/src/app.tsx:111 /settings 路由），点击「质量」页签（core/dashboard/static/src/pages/settings/index.tsx:41、pageLabels.ts:12），断言 admin.code_review.stall_alert_minutes 配置键标签可见（QualityPanel label-note 键名约定，同卡 code-review-scope 等同款）、其 Form.Item 内数字输入框可见可用、点击可聚焦、可输入、无控制台错误（不做保存点击，避免污染用户级配置）。出处：tasks 3.3；【judge 原地修复 2026-09-24】click 前补二次导航重载+wait 10000：上轮已提 wait 20000 仍冷实例首访异步 chunk 渲染竞态超时，重载机制化自愈（断言未动）；【judge 原地修复 2026-09-24 R2】实测根因非渲染竞态而是选择器幻觉属性：浏览器探针 0 控制台错误、11 页签含质量齐全、li[data-menu-id] 全页 22 个均属 v1 外壳——click target 改为 li.ant-menu-item:has-text("质量")（DOM 实测唯一匹配），断言未动；【admin 修复 2026-09-24】移除 visual_baseline 断言（验证基础设施修正，非产品缺陷）：设置表单页天然低对比度——被拒截图 pixel_std=0.0784 险低于健全性门 0.08，同页本轮通过基线 web-quality-facet-aggregate-progress std=0.0808 险过，0.0024 差距属渲染噪声；且截图前刚向输入框键入 25 致画面内容逐轮漂移，基线固化恒处抛硬币态、引擎注记的「后续干净截图轮正常建基线」前提不成立；「输入项在场且可交互」意图由 DOM 六断言完整覆盖，视觉基线无断言价值。断言与步骤未动。 | pass | 0/6 | - |
| api-progress-aggregate-endpoint | 进度端点聚合取值：依赖 cli-progress-shards-realtime-no-main 落的分片夹具（同一 fresh 实例经 scheduling-showcase 项目传递状态），GET /api/code-review/progress?project=scheduling-showcase 返回 running=true、done=26、total=30、current=src/f25.py、review_id 与 review_kind=manual_full。出处：core/dashboard/routes/code_review_routes.py:66-75；spec Scenario 分片进度实时可见 | pass | 0/7 | - |
| web-quality-facet-aggregate-progress | 用户可见终态（本 SPEC 的出发点）：导航 http://127.0.0.1:8787/#/projects/scheduling-showcase（出处 core/dashboard/static/src/app.tsx:103 /projects 路由），点击「代码审查」分面（core/dashboard/static/src/pages/projects/list.tsx:1385-1397），依赖 cli-progress-shards-realtime-no-main 的分片夹具，QualityTab 进度区渲染 审查进行中（全库审查）、26/30 文件、当前：src/f25.py——分片进度经聚合读侧实时上屏。出处：core/dashboard/static/src/pages/projects/components/QualityTab.tsx:850/858/859（进度渲染文本） | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

