# 草稿晋升门控（drafted→ready 晋升门）

<!-- knowledge: capability=draft-promotion-gate rev=3
     sources=spec/archive/2026-09-14-add-draft-promotion-gate,spec/archive/2026-11-16-add-spec-title-promotion-gate,spec/archive/2026-11-27-evo-promotion-lint-wakeup -->

控制 drafted SPEC 是否被自动晋升：`gates.promote_mode` 决定闸口形态（auto 全自动 / manual 人工放行）；晋升链内置机械 lint 门（Deliverables 声明、tasks.md 可解析性、中文标题存在性），保障进入 ready 的 SPEC 内容齐备。lint 拒绝一轮给全可修信息；tasks.md lint 拒绝后修复落盘即时唤醒重评，人工格式失误不转化为 30 分钟量级的管线等待。

## 规则

**闸口形态（gates.promote_mode）**

- 配置键 `gates.promote_mode`，枚举 `auto` / `manual`，缺省 `auto`（与无此键时行为一致）；配置校验拒绝非枚举值并在加载时报错；纳入 Dashboard 受管配置键白名单，支持设置页读写与配置热更新（30s mtime 原地重载）。
- `auto`（或缺省）：晋升链全量执行——软化不可满足声明 + 声明 lint + tasks 可解析性 lint + 中文标题存在性 lint + transition ready + 派发。
- `manual`：晋升闸口关闭——不软化、不 lint、不 transition、不派发；不向 STATE 写 `error`（等待人工放行是设计行为而非故障）；记 info 日志说明该 SPEC 停留 drafted 等待人工放行。
- 闸口覆盖全部 drafted 晋升触发路径：`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入、tasks.md lint 即时唤醒。
- manual 期间不提前执行晋升 lint，因此 lint 违规不会在 drafted 阶段暴露为 error；违规在人工放行时按 manual-spec-promotion 的 lint 规则拦截。
- 从 `manual` 切回 `auto` 后，存量 drafted SPEC 在下一次 full_scan recovery（或新的 drafted 触发）时走完整晋升链自动晋升，无需人工逐个干预。

**tasks.md lint 一次全报**

- tasks.md 可解析性 lint 在分组不可解析时，单条消息并列披露：分组标题形态要求（`## <编号>. <标题>`）、全量 checkbox 任务行计数（item_count，恒可测）与「分组修正后还需为任务行补『组号.序号』编号」的后续提示；item_count 为 0 时不附计数段。分组缺失与任务行缺编号两类失误一轮修完，不要求人工多轮往返。
- 多类 lint 违规（Deliverables 声明 / tasks 可解析性 / 中文标题）由调用方按固定顺序以全角分号聚合成一条 STATE error——Deliverables 段恒居首、tasks 段第二、标题段其后，多类可测信息一次给全。
- lint 判据本身不因报告形态放宽：可解析性硬门与任务行编号规则保持——缺编号任务行仍被拒（防下游静默丢弃）。

**tasks.md 变化即时唤醒**

- status=drafted 且 STATE error 含「tasks.md 可解析性 lint 未通过」段的 spec，其 tasks.md 文件变化即秒级重评晋升（监视粒度 2 秒），不空等 30 分钟 full scan 兜底。
- 唤醒复用既有 `spec_drafted` 恢复出口：start_after 门控与 promote_mode=manual 短路在入口天然生效——manual 档、start_after 未到期的 spec 不因文件变化被唤醒晋升。
- 唤醒名单判据用子串匹配而非前缀：STATE error 是多类 lint 消息按固定顺序的拼接串，Deliverables 段恒居首，「Deliverables+tasks」双违规 spec 的 error 以 Deliverables 段开头，前缀匹配会漏纳该人工起草高发形态；唤醒短语唯一生成点在晋升链 tasks lint 段，子串匹配不误纳其他 drafted 错误。
- 名单覆盖面即 tasks.md lint 族：单族 Deliverables 声明 lint 或中文标题 lint 的 drafted spec 不入名单，其修复落盘仍走 30 分钟兜底节拍。
- 监视卫生：唤醒名单随每轮状态变更处理整体刷新（与 STATE checksum 监视同一轮读数），status 推进或错误清除的 spec 自然出名单；轮询只对名单内 spec 计算 tasks.md checksum，名单外零文件扫描。
- 首见登记不触发：进入名单时只登记当前 checksum 不触发——该内容正是 lint 拒绝的成因，此刻触发只会原样重跑失败 lint；出名单后再入名单同样按首见登记（期间的内容变化由 30 分钟兜底节拍覆盖）。
- 同值抑制：lint 仍败时 STATE error 重写为同值（状态变更仍会刷新名单），tasks.md checksum 未变则不重复触发、不重复打日志；文件内容确实变化才再评，即使 error 终值相同。
- 异常隔离：名单内单条 tasks.md 读取/checksum 异常只记 WARNING 并跳过该条，不汇入全局 STATE watch 的失败退避通道（防单个不可读文件把全局状态监视拖进 2→60s 退避、全量状态事件延迟）；唤醒派发失败同样单条捕获记 WARNING，由 full scan 兜底重试。
- 30 分钟 full scan 兜底节拍对所有 lint 族保留，即时唤醒是叠加通道；程序化起草车道（fenix-new / evo / CLI，经 scheduling_kick 通道）行为不变——即时唤醒只补人工起草车道的恢复盲区。

**中文标题存在性硬门**

- 晋升 lint 链对活跃 `.spec.yaml` 做 title 存在性判定——yaml 解析后 `title` 为非空字符串即通过；`.spec.yaml` 文件缺失、解析失败、字段缺失或值去首尾空白后为空，一律判晋升违规（`drafted + error` 既有形态），由 30 分钟周期扫描自动重试。检查直读活跃侧文件（晋升时 change 目录必在活跃侧，无归档回退分支）。
- 豁免口径：spec 名以精确前缀 `fix-cr-` 开头的 SPEC 豁免（code-fix 通道为程序化模板生成、无 LLM 起草环节，无 title 属合法形态）；不豁免 `fix-*` 泛前缀——手工 fix-* 与 fenix-new、自进化通道同等必填。
- 违规消息处方化：消息内嵌最小写入示例（`title: <5-25字中文标题>` 追加至 `.spec.yaml` 末行）与规范出处（中文标题生成纪律，见 [spec-chinese-title](spec-chinese-title.md)），不留零解释违规；立项方（实现分支或交互会话）补写 title 后，下一次周期扫描重试晋升即通过，无新增人工介入面。
- 门禁只做存在性判定：title 值不做长度/形态校验——5-25 字仍是生成侧纪律，读侧容错契约不变；把形态校验搬进门禁会将展示字段升级为强契约，徒增楔死面。

**清错留痕**

- dashboard 清错端点成功清空 STATE error 时，向与 daemon 同源的项目日志（`.fenix/logs/fenixd.log`，经 project_state_logger 共享 sink）显式写一行留痕：spec 名、清空来源=dashboard、被清 error 摘要（原本为空则注明幂等清除）。dashboard 是独立进程，其 std logging 只进自身日志不汇入 daemon 日志，无此行则清空动作在 daemon 侧不可见。
- 留痕为纯观测行，不改 STATE 写语义（清空仍经 update_spec 原子写回，error 已为空时幂等成功）。

**界面与文档**

- 设置页「审批」页签提供「草稿晋升模式」单选（manual/auto，与 approve_mode 单选同构），位于审批模式设置项上方；说明文字注明 manual 下可经 `/fenix-ready`、项目页按钮或 CLI promote 放行。
- 治理文档（docs/help/06-governance.md）记录人工放行流程；配置文档（docs/help/08-config.md）登记该键取值、缺省与热更新属性。

## 溯源

- 2026-09-14 2026-09-14-add-draft-promotion-gate（spec/archive/2026-09-14-add-draft-promotion-gate） — 新增草稿晋升门控：`gates.promote_mode` 配置、manual 闸口全路径覆盖与零副作用语义、切回 auto 的存量恢复、设置页单选
- 2026-11-06 add-spec-title-promotion-gate（spec/archive/2026-11-16-add-spec-title-promotion-gate/） — 晋升 lint 链追加中文标题存在性硬门：非空 str 判定与违规处方化、`fix-cr-` 精确前缀豁免（不豁免 `fix-*` 泛前缀）、只做存在性不做形态校验
- 2026-11-16 evo-promotion-lint-wakeup（spec/archive/2026-11-27-evo-promotion-lint-wakeup/） — tasks.md lint 一次全报（item_count 并列披露 + 编号后续提示）、lint 拒绝 drafted spec 的 tasks.md 变化即时唤醒（名单预过滤、首见不触发、同值抑制、单条异常隔离）、dashboard 清错显式留痕（共享 sink）
