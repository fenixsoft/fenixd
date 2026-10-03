# 帮助文档机制覆盖（docs/help/）

<!-- knowledge: capability=help-docs-mechanism-coverage rev=1
     sources=spec/archive/2026-10-04-add-help-docs-mechanism-coverage -->

docs/help 帮助文档的机制覆盖面契约：框架演进出的用户可感知机制必须都能在帮助文档中找到可发现的描述与处置入口，文档观测面与代码保持同一代际。各机制自身的业务口径由对应业务域能力页承载，本页只承载文档覆盖契约。

## 规则

- 覆盖判据：用户可感知的重要机制——「验证全绿却停在 testing」「ready 迟迟不派发」「取消后 SPEC 去哪了」「审查误报反复上报」这类用户会遇到、却缺文档解释入口的事项背后的机制——MUST 在 docs/help 有可发现的描述（新小节或既有小节内段落），且每处附权威代码锚点（file:line 形态）供实读核对。判据是「用户遇到这件事时能否从帮助文档找到解释与操作入口」，不是提交历史是否有记载。
- 落位原则：机制描述进其「用户遇到问题时会翻的那一章」——env 豁免握手进验证体系章、瞬断解封进瞬断治理节、取消保持态进生命周期章并与 Dashboard「恢复运行」操作互为入口、质量门禁在 Dashboard 章与验证章交叉承载；禁止集中新建「新机制汇总」章。帮助中心的组织轴是使用场景，不是提交历史（ADR-225）。
- 篇幅纪律：每项机制一段到一小节，先「用户看到什么/该做什么」再机制细节（用户视角两段式）；禁止整段搬运 SPEC 设计文档。长机制（code-fix 车道、质量门禁整链、会话接入分面）允许独立小节，但以两段式为上限结构。
- 数值与名称锚点纪律：写进文档的每个缺省值、秒数、上限 MUST 实读代码锚点核对，代码与记载不符时以代码为准；UI 名称（分面 label、页面级页签名、设置页页签数）以前端代码字面为准实读后写入，不凭文本转抄（前端可能继续演进）。
- 锚点防漂移：新增小节放在相关既有小节之后、不改既有标题文本，既有相对链接与锚点保持有效。
- 结构边界：04-cli 托管态三态表与 bin/ 辅助脚本表是两个独立表格——脚本行不入托管态表，bin/ 表带用途列且含 fenix_cli.py（promote/reflow/activate/review/unfreeze 子命令）等用户可用主要脚本；12-faq 标题编号连续无重复；08 章文档区表述分两层——文档弹窗 5 页签（需求背景/详细设计/任务清单/测试场景清单/验证报告）与 SPEC 详情页页面级 5 页签（运行时间轴/场景结果/Bug 列表/失败截图/Hook），不混排。

## 当前覆盖面

按章的机制覆盖现状（各机制的数值口径见对应业务域能力页）：

- 05 验证体系：env 豁免 admin 握手两级防线、fastlane 小缺陷轻量通道、judge 重裁决治理与 verdict 缓存、迟到 verifier 结果丢弃、逐测超时门（pytest 单用例硬门 + timeout-allowlist 豁免登记）、infra 失败预算豁免、parallel_plan.json 并行出题产物。
- 06 调度与治理：run 止损三件套、瞬断解封渐进恢复态序、信号死法冷却、SPEC 并发在飞守卫、infra 预算豁免对账字段。
- 03 生命周期：取消保持态 `_cancelled_hold` 与「恢复运行」动作。
- 07 保障机制：stash pop 冲突三分诊、merge-back spec 目录在飞顺延守卫、relocation writeback 同层修正、请求型信号前置探测与处置回写、告警降噪治理、陈旧悬空超时硬上限。
- 08 Dashboard：五个分面名称（功能开发/代码审查/测试回归/项目架构/会话接入）、会话接入分面全貌（显式启动、SSE 实时流、composer 斜杠命令与 `@` 文件补全、草稿持久化、空闲回收）、SPEC 详情页页面级页签全集、质量门禁 Card、运行记录降噪+聚合+向前分页、SPEC 列表筛选 URL sticky、回归分面「自动修复回归问题」按钮、代码审查分面五动作（含 fenix-ignore 注释固化误报裁决与触发受理三态回链）、详情行工具条「恢复运行」。
- 09 配置：配置键以「键｜默认值｜范围｜生效方式」键表行进入全键参考（timeout_overrides、impl_run_budget_max、verify_redo_budget、transient_unseal_* 五键、run_stall_budget_* 三键、max_dangling_seconds、code_review.scope/stall_alert_minutes、review_stall_minutes、mergeback_wip_orphan_grace_minutes、repo_code_review_concurrency、impl_code_review_mode、impl_code_review_lane_timeout_sec），默认值与代码缺省一致。
- 10/11 数据地图：STATE.md 关键内部字段清单（注明 `_` 前缀字段无条件透传持久化）与 `.fenix/` 文件地图收录 parallel_plan.json、fastlane_decision.json、quality-gates.json、architecture/、code-review 分片与 fix-* 台账、spec_delete_request.json、restart_history.jsonl、supervisor_runtime.json、scheduling_kick/ 等。
- 12 FAQ：「烧钱快」条目处置附 run 止损指引（`agents.run_stall_budget_*` 缺省关闭，开启后停滞 run 自动终止）；SPEC 卡 ready 根因按宽松优先级调度口径表述。

## 溯源

- 2026-10-04 add-help-docs-mechanism-coverage（spec/archive/2026-10-04-add-help-docs-mechanism-coverage） — 新建本能力：把文档观测面补齐到与代码同一代际——26 项缺失机制补节（验证链新机制、治理与守护新机制、取消保持态、保障细化、质量门禁整链、会话接入分面、运行记录可读性、code-fix 车道全机制、fenix-ignore 与触发受理回链）、缺失配置键与 STATE 字段/文件地图补全、04/08/12 三处结构修复、UI 名称校准；确立覆盖判据、按使用场景落位、两段式篇幅上限与数值/名称锚点纪律
