# 验证报告：add-spec-chinese-title

> ⚠️ 本报告由框架于 2026-11-06T09:23:08Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-06T09:23:07.305767+00:00+run-result@mtime1793956987354364615

## 结论：✅ 通过（verified）

**状态：verified — 22/22 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 22/22 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 22 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.18M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fixture-title-seed | 夹具中文标题数据种子（幂等）：scheduling-showcase 8 个活跃 spec 的 STATE 基线由 prepare 层供给但无 .spec.yaml title——本场景为 c-sched-set 写入 title「调度脚本演示集」、c-sched-clear 写入 title「清理调度积压」（后者供无标题回归链剥离），并合成归档条目 f-arch-title（spec/archive/2026-01-02-f-arch-title/.spec.yaml title「归档标题回退验证」+ .fenix/STATE.archive.md 清单条目）供归档回退与 SummaryIndex 归档映射验证；同时幂等移除用户级 dashboard.yaml ignored 列表中的夹具路径（历史删除类场景写入且跨轮持久，prepare 层只登记不解除 ignored）。夹具根经 FENIX_FIXTURE_ROOT 注入，缺省 /root/scheduling-showcase。 | pass | 0/6 | - |
| backend-read-probe-tolerance | read_spec_title 读侧容错矩阵 + summary/detail 透传直测（tasks 1.1/1.2 的函数契约，进程内探针、合成 tmp 项目根零存量污染）：活跃有/无 title 字段、文件缺失、YAML 解析失败、非法 spec 名、归档目录有/无 title 共 7 形态 → None/值语义（全容错不抛异常）；spec_summary 与 spec_detail 对有/无 title 条目分别透传 string/null。run cwd=验证树根，import core 直测实现分支。 | pass | 0/2 | - |
| backend-pytest-spec-title | 实现侧单测门（tasks 1.3 tests/test_spec_title.py）：读侧容错矩阵（活跃/归档有/无 title、文件缺失、字段缺失、YAML 损坏、非法 spec 名 → None）与 spec_summary/spec_detail 透传形状由实现单测钉死，本场景跑通该文件。仅 -v 无 -q（pytest 9 下 -q 覆盖 -v 退化为点输出、不打印 PASSED，output_match 全场景同因伪失败）。 | pass | 0/2 | - |
| evo-materialize-title-probe | evo 通道 materialize_draft title_cn 契约直测（tasks 3.2、design D6）：title_cn 合法（5-25 字）→ 落盘 .spec.yaml 含 title 行；缺 title_cn 与非法形态（<5 字）→ 草稿不作废、仅省略 title 行（容错缺省对齐读侧）。进程内探针写 tmp 草稿根，零存量污染；run cwd=验证树根。 | pass | 0/2 | - |
| evo-pytest-contract | evolution 既有单测回归门（tasks 3.2 要求补/改单测钉死契约含缺 title_cn 容错分支）：跑通 tests/test_self_evolution.py 与 tests/test_dashboard_evolution_api.py（materialize_draft 既有覆盖所在）。仅 -v 无 -q（-q 并列会使 PASSED 不打印、output_match 全场景同因伪失败）。 | pass | 0/2 | - |
| frontend-tests-subtitle | 前端副标题单测门（tasks 2.4 core/dashboard/static/tests/specTitleSubtitle.test.mjs）：两处副标题渲染（有 title / 无 title / 树形缩进对齐）与搜索命中中文标题由实现单测钉死，本场景跑通该文件（node --test，摘要行含 fail 0）。 | pass | 0/2 | - |
| backfill-fulltree-audit | 存量回填全量自检（spec-chinese-title「全量回填完成」+「回填幂等」机械验收；裁决修复：审计范围对齐 design D7「清单冻结于立项时刻」与 Risks「新建 spec 无标题→残余缺口零破坏」——以回填收尾自检提交 7e21f2dcc（16:17:30，536/536 零违规）为冻结口径：冻结清单内目录全量断言 .spec.yaml 存在、YAML 可解析、title 非空 5-25 字、恰一条 title: 行；收尾后并发新增目录透明豁免并逐条 POST-FREEZE-SKIP 列出（仍要求文件存在且 YAML 可解析），git 不可用即脚本崩溃失败不豁免）：任一冻结清单违例逐条列出并非零退出；run cwd=验证树根（实现分支的回填数据面）。 | pass | 0/2 | - |
| channel-discipline-docs | 立项通道起草纪律落文档（tasks 3.1/3.2）：skills/fenix-new/SKILL.md 同阶段生成 5-25 字中文标题并给出 .spec.yaml title 写入示例（与 mode 写入同模式）；agents/evolution.md 起草契约含 title_cn 字段与 5-25 字要求。grep 哨兵链逐文件校验（关键词锚点取任务文本自带的确定性词）。 | pass | 0/2 | - |
| v1-row-subtitle-render | v1 SPEC 列表名称列中文副标题渲染：夹具 c-sched-set 行（.spec.yaml title「调度脚本演示集」）在英文名主行下方渲染中文副标题（行内文本含标题即证副标题已落名称列），无 .spec.yaml 的 c-frozen-a 行保持正常渲染。行寻址经 antd rowKey（出处 routes.ts:52 /projects/:name、list.tsx:790 名称列、list.tsx:1037 rowKey="name"、SpecNameCell list.tsx:263-289）。 | pass | 0/4 | - |
| v1-search-hits-title | v1 名称关键字搜索命中中文标题：搜索框（placeholder「搜索名称…」list.tsx:982）键入仅存在于 title 的关键字「调度脚本演示集」（条目英文名 c-sched-set 不含该串），防抖 ≥300ms（list.tsx:88/1100）后本地过滤保留该条目、未命中条目被滤除且行数=1；过滤纯前端不发起服务端请求、排序键不受影响（dashboard-spec-table 既有契约延续，list.tsx:1341 kw 过滤分支 OR title 命中；出处 routes.ts:52 /projects/:name）。 | pass | 0/5 | - |
| v1-mobile-card-subtitle | v1 移动端（<768px，390×844）卡片形态名称区副标题同规则（tasks 2.2、design D5）：卡片列表 SpecCardList（list.tsx:590）复用 SpecNameCell（list.tsx:638），c-sched-set 卡片内渲染中文副标题；c-frozen-a 卡片不含他条目标题文本（缺失不渲染）。（出处 routes.ts:52 /projects/:name） | pass | 0/4 | - |
| v1-mobile-card-click-detail | v1 移动卡片名称点击交互不变（交互契约候选 cards 的交互覆盖，tasks.md:1109）：点击 c-sched-set 卡片名称 span[role=button]（SpecNameCell list.tsx:272-289 history.push）落地 SPEC 详情路由 /projects/:name/:spec（routes.ts:40）；副标题不承载独立点击目标、行点击行为与改动前一致。 | pass | 0/3 | - |
| v1-untitled-presence-clear | 无标题回归链上篇（剥离基线）：c-sched-clear 行（seed 已写入 title「清理调度积压」）行内渲染副标题文本；同页无 .spec.yaml 的 c-frozen-a 行不含该标题文本（null 条目零渲染的他条目对照）。（出处 routes.ts:52 /projects/:name、list.tsx:1037 rowKey="name"） | pass | 0/4 | - |
| v2-table-subtitle-desktop | v2 项目详情 SPEC 表名称列中文副标题（v2-commercial-ui 修改需求，design D5）：桌面表格（projectDetail.tsx:405 data-proto-id=pd-table、:191-203 名称单元格 span.v2-ellipsis）c-sched-set 行英文名下方渲染次级中文副标题；c-frozen-a 行不含该文本（null/空不渲染、保持单行）；表格列集与行寻址不变。（出处 routes.ts:90-91 /v2/projects/:name） | pass | 0/4 | - |
| v2-table-subtitle-mobile-cards | v2 移动形态 SPEC 卡片流回归钉死（裁决修复：原 text_match 越出 spec 冻结范围——tasks 2.3 将 v2 改动钉在 SPEC 表格名称列、2.2 才显式含 v1 移动卡片、2.4「两处副标题渲染」，场景描述自书「窄屏卡片形态不受影响」，projectDetail.tsx 移动卡片分支 310 起无副标题为冻结范围内合法形态）：c-sched-set 卡片可见且不含标题文本（卡片流行为不变）；c-frozen-a 卡片不含他条目标题文本（null 条目零渲染）。（出处 routes.ts:90-91 /v2/projects/:name） | pass | 0/4 | - |
| v2-name-click-lands-detail | v2 名称单元格既有交互不变：点击 c-sched-set 名称 span.v2-ellipsis（projectDetail.tsx:195-199 onClick navigate）落地 /v2/projects/:name/:spec（routes.ts:86-87、specDetail.tsx:125 data-proto-id=sd-info）；副标题不承载独立点击目标、跳转行为与改动前一致。 | pass | 0/4 | - |
| api-specs-list-title-passthrough | /api/specs 列表项透传 title（base.py:673 路由、spec_routes.py:76 _api_specs、summary.py:346 spec_summary）：全条目携带 title 键（items required 无遗漏）、c-sched-set title 精确等于种子值；归档清单条目 f-arch-title（archived=true）经 SummaryIndex 归档目录映射（design D3 单次 scandir，MUST NOT per-spec glob）透传标题。URL origin 由框架改写。 | pass | 0/3 | - |
| api-spec-detail-active-title | /api/specs/<spec> 详情透传 title 且英文名寻址不变（base.py:675 路由、spec_routes.py:125 _api_spec_detail、summary.py:1011 spec_detail）：以英文名 c-sched-set 寻址 200、name 字段不变、title 精确透传——标题不参与寻址（id/name 关系）的回归点：一切输入与寻址仍以英文名为唯一键。 | pass | 0/3 | - |
| api-spec-detail-archived-title | 已归档 SPEC 详情 title 归档回退读取（spec_docs.py:103 resolve_spec_dir 归档日期前缀模式匹配、活跃优先归档回退）：英文名 f-arch-title 寻址命中 spec/archive/2026-01-02-f-arch-title/.spec.yaml 的 title「归档标题回退验证」。 | pass | 0/2 | - |
| fixture-title-strip-clear | 无标题回归链中篇：把夹具 c-sched-clear/.spec.yaml 的 title 行剥离（保留 schema/created/mode 脚手架），模拟存量「无 title 字段」条目；文件 mtime 变化令读侧签名缓存（(path, mtime_ns, size)，同 spec_mode 模式）失效、下次读取回到 null。幂等可重入。 | pass | 0/2 | - |
| v1-untitled-absence-single-line | 无标题条目保持单行 + 缺失容错端到端（dashboard-spec-table「无标题条目保持单行」、读侧返回 null → 前端零渲染）：title 剥离后重新加载列表，「清理调度积压」文本从页面消失（副标题行不渲染），c-sched-clear 行仍渲染英文名主行（布局未破坏），活跃条目行数不变（8 行，归档清单条目默认视图不出现）。（出处 routes.ts:52 /projects/:name、list.tsx:1037 rowKey="name"、spec_docs.py:103 resolve_spec_dir） | pass | 0/4 | - |
| api-specs-title-null-entries | 缺失容错 null 形状（读侧容错不抛异常、API 条目 title 为 null）：无 .spec.yaml 的 c-frozen-a 与 title 行被剥离的 c-sched-clear 条目 title=null；全条目仍携带 title 键（透传形状 string\|null 的 null 半边，字段不缺位）。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 22 个（第 1 轮）。

- 首轮写入 22 个场景

