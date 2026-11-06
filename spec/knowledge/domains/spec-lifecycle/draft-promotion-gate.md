# 草稿晋升门控（drafted→ready 晋升门）

<!-- knowledge: capability=draft-promotion-gate rev=2
     sources=spec/archive/2026-09-14-add-draft-promotion-gate,spec/changes/add-spec-title-promotion-gate -->

控制 drafted SPEC 是否被自动晋升：`gates.promote_mode` 决定闸口形态（auto 全自动 / manual 人工放行）；晋升链内置机械 lint 门（声明、tasks 可解析性、中文标题存在性），保障进入 ready 的 SPEC 内容齐备。

## 规则

- 配置键 `gates.promote_mode`，枚举 `auto` / `manual`，缺省 `auto`（与无此键时行为一致）；配置校验拒绝非枚举值并在加载时报错；纳入 Dashboard 受管配置键白名单，支持设置页读写与配置热更新（30s mtime 原地重载）。
- `auto`（或缺省）：晋升链全量执行——软化不可满足声明 + 声明 lint + tasks 可解析性 lint + 中文标题存在性 lint + transition ready + 派发。
- `manual`：晋升闸口关闭——不软化、不 lint、不 transition、不派发；不向 STATE 写 `error`（等待人工放行是设计行为而非故障）；记 info 日志说明该 SPEC 停留 drafted 等待人工放行。
- 闸口覆盖全部 drafted 晋升触发路径：`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入。
- manual 期间不提前执行晋升 lint，因此 lint 违规不会在 drafted 阶段暴露为 error；违规在人工放行时按 manual-spec-promotion 的 lint 规则拦截。
- 从 `manual` 切回 `auto` 后，存量 drafted SPEC 在下一次 full_scan recovery（或新的 drafted 触发）时走完整晋升链自动晋升，无需人工逐个干预。
- **中文标题存在性硬门**：晋升 lint 链对活跃 `.spec.yaml` 做 title 存在性判定——yaml 解析后 `title` 为非空字符串即通过；`.spec.yaml` 文件缺失、解析失败、字段缺失或值去首尾空白后为空，一律判晋升违规（`drafted + error` 既有形态），由 30 分钟周期扫描自动重试。检查直读活跃侧文件（晋升时 change 目录必在活跃侧，无归档回退分支）。
- **豁免口径**：spec 名以精确前缀 `fix-cr-` 开头的 SPEC 豁免（code-fix 通道为程序化模板生成、无 LLM 起草环节，无 title 属合法形态）；不豁免 `fix-*` 泛前缀——手工 fix-* 与 fenix-new、自进化通道同等必填。
- **违规消息处方化**：消息内嵌最小写入示例（`title: <5-25字中文标题>` 追加至 `.spec.yaml` 末行）与规范出处（中文标题生成纪律，见 [spec-chinese-title](spec-chinese-title.md)），不留零解释违规；立项方（实现分支或交互会话）补写 title 后，下一次周期扫描重试晋升即通过，无新增人工介入面。
- **门禁只做存在性判定**：title 值不做长度/形态校验——5-25 字仍是生成侧纪律，读侧容错契约不变；把形态校验搬进门禁会将展示字段升级为强契约，徒增楔死面。
- 设置页「审批」页签提供「草稿晋升模式」单选（manual/auto，与 approve_mode 单选同构），位于审批模式设置项上方；说明文字注明 manual 下可经 `/fenix-ready`、项目页按钮或 CLI promote 放行。
- 治理文档（docs/help/06-governance.md）记录人工放行流程；配置文档（docs/help/08-config.md）登记该键取值、缺省与热更新属性。

## 溯源

- 2026-09-14 2026-09-14-add-draft-promotion-gate（spec/archive/2026-09-14-add-draft-promotion-gate） — 新增草稿晋升门控：`gates.promote_mode` 配置、manual 闸口全路径覆盖与零副作用语义、切回 auto 的存量恢复、设置页单选
- 2026-11-06 add-spec-title-promotion-gate（spec/changes/add-spec-title-promotion-gate/） — 晋升 lint 链追加中文标题存在性硬门：非空 str 判定与违规处方化、`fix-cr-` 精确前缀豁免（不豁免 `fix-*` 泛前缀）、只做存在性不做形态校验
