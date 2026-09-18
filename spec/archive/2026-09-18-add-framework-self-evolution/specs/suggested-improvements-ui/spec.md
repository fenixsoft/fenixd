# suggested-improvements-ui Spec

## ADDED Requirements

### Requirement: 设置页「自进化」页签与卡片布局

Dashboard 设置页 MUST 把既有页签文案「自愈」改为「自进化」，并在该页签下自上而下渲染两个面板：

1. 既有「代码陈旧自愈」面板（`StaleCodeSelfhealPanel`，标题、开关/输入控件、控件 `data-testid` 与绑定配置键全部不变；其原有卡片内保存按钮 MUST 上提到页签底部，见下条）；
2. 新增「建议改进项」面板（`SuggestedImprovementsPanel`）——标题「建议改进项」MUST 置于卡片**外**（与第一张面板同构），标题下 MUST 有该面板的功能注解文字；其配置卡片内 MUST NOT 再重复标题、MUST NOT 自带保存按钮；面板下半部的「条目列表」小节标题与表格同样 MUST 置于卡片**外**（见「建议改进项表格」）。

页签底部 MUST 只有**唯一一个**「保存」按钮，置于页签内容最下方、右对齐（与其它页签的保存位置一致）。点击该按钮 MUST 同时校验并收集两张卡片各自的配置节，合并为**一次** `POST /api/config` 请求提交；任一张卡片校验失败 MUST 中止提交且 MUST NOT 发出请求。

页签在用户级与项目级作用域下 MUST 均可见（沿用既有页签构造方式），作用域切换 MUST NOT 丢失或错位这两张卡片。页签内部键的改名 MUST NOT 破坏页面默认选中态与其它页签。

#### Scenario: 页签文案为「自进化」

- **WHEN** 用户打开设置页
- **THEN** 菜单中出现文案为「自进化」的页签（不再出现「自愈」），点击后进入该页签

#### Scenario: 两张卡片按序渲染

- **WHEN** 用户在「自进化」页签下查看内容
- **THEN** 第一张卡片是「代码陈旧自愈」（含既有开关与秒数输入），第二张卡片是「建议改进项」

#### Scenario: 第二张卡片标题在卡片外

- **WHEN** 用户在「自进化」页签下查看「建议改进项」卡片
- **THEN** 标题「建议改进项」渲染在卡片外（与「代码陈旧自愈」同构），标题下方有功能注解，卡片内不再重复标题

#### Scenario: 页签底部唯一保存按钮

- **WHEN** 用户在「自进化」页签下查看页面
- **THEN** 全页只有页签内容最下方、右对齐的一个「保存」按钮，两张卡片内均不再各带保存按钮

#### Scenario: 一次保存提交两张卡片

- **WHEN** 用户修改「代码陈旧自愈」与「建议改进项」两处配置后点击该保存按钮
- **THEN** 只发出一次 `POST /api/config`，载荷同时含 `stale_code_selfheal` 与 `self_evolution` 两节，保存成功后回显新值

#### Scenario: 既有自愈面板不回归

- **WHEN** 在用户级或项目级作用域下查看「代码陈旧自愈」卡片
- **THEN** 开关控件、数值输入、缺省值 120 与非法值后端拒绝行为与改动前完全一致；保存入口为页签底部唯一保存按钮（一次提交覆盖本卡片），卡片内无独立保存按钮

### Requirement: 全局开关与每轮上限

「建议改进项」配置卡片 MUST 提供：

- 开关「允许框架自改进」，绑定 `self_evolution.auto_accept`（缺省关闭）。MUST 采用开关行布局——开关控件在前、名称紧随其后**同行且不换行**，名称后附 `（self_evolution.auto_accept）` 键名注解；开关行下方 MUST 有该开关的功能注解文字；
- 数值输入「每轮分析条目上限」，绑定 `self_evolution.max_items_per_run`（整数，1..200，缺省 20）。MUST **独占一行**（MUST NOT 与开关同排展示），输入框 MUST 带单位后缀「条」，其下 MUST 有该输入的功能注解文字。

两者的读值 MUST 取自配置接口返回的 `self_evolution` 节点。保存 MUST 经页签底部唯一保存按钮走既有配置写入路径且**不带 `project` 参数**（写用户级），保存成功后有成功提示并回显新值。

在项目级作用域下，两项控件 MUST 置为只读并展示提示「全局键，请在用户级作用域修改」，MUST NOT 允许在此作用域提交 `self_evolution`（此时页签底部保存按钮仍在，但载荷 MUST NOT 含 `self_evolution`，仅可提交项目级可写的 `stale_code_selfheal`）。后端拒绝（400）时前端 MUST 展示可读错误文案且不改动本地状态。

#### Scenario: 控件排布与注解

- **WHEN** 用户在用户级作用域查看「建议改进项」配置卡片
- **THEN** 「允许框架自改进」为开关行（开关与名称同行不换行）且下方有功能注解；「每轮分析条目上限」独占一行、输入框单位后缀为「条」且下方有功能注解

#### Scenario: 用户级作用域读写往返

- **WHEN** 用户在用户级作用域把开关打开并保存
- **THEN** 请求写给用户级配置，保存成功后重新读取显示为开启；后端配置文件中 `self_evolution.auto_accept` 为 `true`

#### Scenario: 项目级作用域只读提示

- **WHEN** 用户切换到项目级作用域查看「建议改进项」卡片
- **THEN** 开关与上限输入置为只读，并显示「全局键，请在用户级作用域修改」提示；此时点击页签底部保存按钮，提交载荷 MUST NOT 含 `self_evolution`


#### Scenario: 非法值被拒绝且提示

- **WHEN** 上限输入被提交为 0 / 负数 / 超过 200
- **THEN** 后端返回 400，前端展示可读错误，界面值 MUST NOT 被改动为非法值

### Requirement: 清理所有项目自省内容

「建议改进项」配置卡片内 MUST 提供一个**全局**动作按钮「清理所有项目自省内容」，置于配置表单**之外**（`Form` 的 `disabled` 只作用于表单控件，普通按钮置于表单内不会随作用域禁用）：

- 按钮 MUST 为**实心红底白字**告警样式（`type="primary"` + `danger`，与「批量删除」同款），并带该动作的功能注解文字；
- 点击 MUST 先弹二次确认，确认文案 MUST 明示三点：清空所有项目的 `.fenix/todo.md`、**下方条目列表不受影响**（列表读 `items.jsonl`）、不代为提交 git；
- 确认后调用 `POST /api/evolution/clear-todo`（**不带 `project` 参数**，全局动作），完成后 MUST 以提示回报「已清空 N / 跳过 M / 失败 K 个」，存在失败项时 MUST 逐个列出项目名与错误；
- 清空后 MUST NOT 重新拉取条目列表（`items.jsonl` 未变，列表本就无变化）；
- 在项目级作用域下按钮 MUST 置为禁用（全局动作，与卡片其余配置项的项目级只读语义一致）；
- 清空 MUST 只影响各项目 `.fenix/todo.md`（截断为空文件、保留文件本体），MUST NOT 触碰 `.fenix/evolution/` 下的 `items.jsonl` / 草稿 / 水位，也 MUST NOT 代各项目提交或推送 git。

后端 `POST /api/evolution/clear-todo` MUST 遍历 registry 已发现且存在的项目逐个清理，单个项目失败 MUST NOT 中断其余：返回 `{ok, cleared: [项目名], skipped: [{project, reason}], failed: [{project, error}]}`，无失败项时 `ok` 为 `true`（全部跳过亦为 `true`）。项目无 `.fenix/` 目录或 todo.md 本就不存在时 MUST 计入 `skipped`（MUST NOT 为其凭空创建目录）。清空 MUST 与每日自省追加、自进化标记回写共用同一把 todo.md flock。

#### Scenario: 有待清理内容时的确认与执行

- **WHEN** 用户在用户级作用域点击「清理所有项目自省内容」并在确认弹窗中确认
- **THEN** 发出一次 `POST /api/evolution/clear-todo`（无 `project` 参数），各项目 `.fenix/todo.md` 被截断为空文件且文件仍在，提示回报已清空的项目数；下方条目列表的条数 MUST NOT 变化

#### Scenario: 无 todo.md 的项目计入跳过

- **WHEN** 某已发现项目的 `.fenix/todo.md` 不存在（或无 `.fenix/` 目录）
- **THEN** 该项目计入 `skipped` 并附原因，MUST NOT 为其创建任何目录，也 MUST NOT 使请求失败

#### Scenario: 项目级作用域禁用

- **WHEN** 用户切换到项目级作用域查看「建议改进项」卡片
- **THEN** 「清理所有项目自省内容」按钮为禁用态，点击不产生任何请求

#### Scenario: 单项失败不中断其余

- **WHEN** 某个项目的 todo.md 因权限/IO 原因清空失败
- **THEN** 其余项目仍被正常清空，响应 `ok` 为 `false` 且 `failed` 列出该项目与错误，前端以错误提示展示明细

### Requirement: 建议改进项表格

表格 MUST 直接置于页签内容流内（MUST NOT 包在卡片里），小节标题「条目列表」以与「建议改进项」同级的标题形式置于表格上方。数据来自 `GET /api/evolution/items`。列 MUST 依次为：**复选框、项目、日期、类别、问题、评估结论、状态、操作**。

- 首列 MUST 为行选择复选框（表头全选框随当前过滤结果全选/半选）；
- 类别列 MUST 显示 todo.md 的小节名（浪费 / 失误 / 可改进），并以 `Tag` 渲染（写法参照 SPEC 列表页「模式」列）；
- 问题列 MUST 显示条目标题；
- 评估结论列 MUST 汇总三项判定（问题是否成立 / 建议是否合理 / 是否值得立项），未超过一屏时可截断但 MUST 可经「查看分析结论」看到全文；
- 状态列 MUST 显示中文文案映射：待决策 / 不需要立项 / 草稿生成失败 / 已同意 / 已自动接受 / 已拒绝 / 接受失败；
- 默认按入库时间倒序；列表为空时 MUST 显示空态文案（如「暂无建议改进项」）而非空白；
- 接口失败时 MUST 显示可读错误且页面其它区块不受影响。

表头 MUST 支持排序：项目 / 日期 / 类别 / 问题 / 状态五列可排序，评估结论与操作列 MUST NOT 排序。日期按 `date_section`（ISO 串，字典序即时间序）排序；状态 MUST 按**语义次序**排序（待人工处理的在前、终态在后），MUST NOT 用标签文本的字母序。

移动端 MUST 以横向滚动展示表格并把操作列固定在右侧；本 SPEC 不要求卡片式降级布局。

#### Scenario: 表格列与顺序

- **WHEN** `/api/evolution/items` 返回若干条目
- **THEN** 表格按「复选框 / 项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作」顺序渲染，且默认按入库时间倒序

#### Scenario: 表头排序

- **WHEN** 用户点击「日期」表头
- **THEN** 表格按 `date_section` 升序重排；再点一次转为降序；点击「状态」表头时按语义次序（待决策等未决状态在前）而非标签字母序

#### Scenario: 类别列以 Tag 渲染

- **WHEN** 条目类别为「浪费 / 失误 / 可改进」
- **THEN** 该列以 `Tag` 组件渲染（非纯文本），未知类别以默认色 Tag 兜底

#### Scenario: 状态文案映射

- **WHEN** 条目状态为 `pending` / `analyzed` / `draft_failed` / `accepted` / `auto_accepted` / `rejected` / `accept_failed`
- **THEN** 分别显示「待决策 / 不需要立项 / 草稿生成失败 / 已同意 / 已自动接受 / 已拒绝 / 接受失败」

#### Scenario: 空态

- **WHEN** 尚无任何建议改进项
- **THEN** 表格区域显示空态文案，MUST NOT 显示空白或报错

#### Scenario: 移动端可横向滚动且操作列固定

- **WHEN** 在窄屏（移动端断点）下查看表格
- **THEN** 表格可横向滚动，操作列始终可见（固定在右侧）

### Requirement: 过滤条

表格上方 MUST 有过滤条，控件依次为：**状态（下拉）、项目（下拉）、日期区间（RangePicker）、「重置」**。

- 状态下拉的**缺省值随数据重算**：条目列表中只要存在「待决策」（`pending`）条目，状态条件缺省即取 `pending`（把待用户决策的条目顶到眼前）；一条 `pending` 都没有时状态条件缺省为空，此时表格不做任何过滤、原样展示全部条目。该重算在每次数据重载时进行（无粘性：不做用户接管标记），用户手动改动筛选后保留到下一次数据重载为止；
- 状态与项目下拉的选项 MUST 从当前数据现算 distinct 值（MUST NOT 出现选了必然 0 条的选项）；当前选中值 MUST 始终出现在选项里（否则选项随数据变化消失时，下拉会把原始值当标签渲染出来）；
- 日期区间 MUST 按 `date_section` 做闭区间过滤；
- 过滤 MUST 在前端完成（对已加载列表过滤，MUST NOT 因过滤重复请求接口）；
- 「重置」MUST 仅在任一过滤条件非空时出现，点击后清空全部三个条件（回到无过滤态）；
- 过滤无结果时 MUST 显示区别于「暂无任何条目」的空态文案。

#### Scenario: 存在待决策条目时缺省聚焦待决策

- **WHEN** 用户打开「自进化」页签，且条目列表中至少有一条「待决策」条目
- **THEN** 状态下拉显示「待决策」，表格只展示「待决策」条目（过滤条其它条件为空）

#### Scenario: 无待决策条目时缺省不过滤

- **WHEN** 用户打开「自进化」页签，且条目列表中没有任何「待决策」条目（如全部已决策/不需要立项）
- **THEN** 状态下拉为空（占位文案），表格原样展示全部条目

#### Scenario: 数据重载后重算缺省状态

- **WHEN** 用户停留在「自进化」页签，触发一次数据重载（如完成一次批量同意使最后一条 `pending` 消失）
- **THEN** 状态下拉重算为「无 `pending` 即不过滤」，表格展示全部条目；若重载后仍有 `pending`，状态下拉回到「待决策」

#### Scenario: 按项目与日期过滤

- **WHEN** 用户选择某项目并选择一段日期区间
- **THEN** 表格只展示该项目且 `date_section` 落在该区间内（含端点）的条目；「重置」出现，点击后回到缺省过滤

#### Scenario: 过滤不触发额外请求

- **WHEN** 用户切换任一过滤条件
- **THEN** MUST NOT 产生新的 `/api/evolution/items` 请求（纯前端过滤）

### Requirement: 多选与批量操作

表格上方 MUST 提供「批量同意 / 批量拒绝 / 批量删除」三个按钮，作用于当前勾选的条目；未勾选任何条目时 MUST 禁用。

- 批量 MUST 逐个调用既有单条接口（后端无批量端点），MUST **串行**执行（并发写 `items.jsonl` 与逐条 git commit 会互相冲突）；
- 执行前 MUST 有二次确认弹窗，预告「将执行 N 条」；对状态不允许该操作的条目 MUST 在前端筛掉并在弹窗中预告「跳过 M 条」及其原因分组（如「已决策 2 条、不需要立项 1 条」）；全部被跳过时 MUST NOT 发起请求；
- 执行后 MUST 汇报「成功 X 条 / 跳过 Y 条 / 失败 Z 条」，失败明细 MUST 逐条列出条目名与后端错误；
- 执行后 MUST 刷新列表并清空勾选；
- 过滤条件变化时 MUST 清空勾选（MUST NOT 让批量作用到当前不可见的行上）。

#### Scenario: 勾选后批量同意

- **WHEN** 用户勾选若干待决策条目并点击「批量同意」
- **THEN** 出现确认弹窗预告将处理的条数；确认后逐条调用接受接口，完成后提示成功条数并刷新列表，勾选被清空

#### Scenario: 不可执行条目被跳过并预告

- **WHEN** 勾选中混有 `analyzed`（不需要立项）或已决定状态的条目
- **THEN** 确认弹窗 MUST 预告跳过的条数与原因分组，且 MUST NOT 对这些条目发起请求

#### Scenario: 执行中禁止重复提交

- **WHEN** 批量正在执行
- **THEN** 三个批量按钮 MUST 处于禁用/加载态，重复点击 MUST NOT 产生第二轮请求

#### Scenario: 改过滤清空勾选

- **WHEN** 用户已勾选若干行，随后改动任一过滤条件
- **THEN** 勾选被清空，批量按钮回到禁用态

### Requirement: 操作列「更多」下拉

操作列 MUST 使用与 SPEC 列表页「更多」按钮一致的交互形态（antd `Dropdown` + `MoreOutlined` 图标 + `Button type="link" size="small"`），菜单项 MUST 依次为：查看分析结论、查看 SPEC 草稿、同意、拒绝（危险项）、删除（危险项）。

禁用规则：

- 无草稿的条目（状态 `analyzed` / `draft_failed`）：「查看 SPEC 草稿」与「同意」MUST 禁用，「查看分析结论」与「拒绝」保持可用（`analyzed` 的「拒绝」MUST 禁用，改为仅可查看结论）；
- 已决定条目（`accepted` / `auto_accepted` / `rejected`）：「同意」与「拒绝」MUST 禁用，查看类项保持可用；
- 「删除」MUST NOT 设状态门——任意状态（含 `accepted` / `auto_accepted`）均可删除。

「同意」「拒绝」「删除」MUST 经二次确认弹窗后才发起请求，MUST NOT 单击即执行。删除的确认弹窗 MUST 明示后果：条目将从列表移除、草稿一并删除，且其 todo.md 记录仍存在、可能在下一轮分析 run 中重新入库。

#### Scenario: 菜单五项与顺序

- **WHEN** 用户点击某条 `pending` 条目的操作按钮
- **THEN** 弹出菜单，依次为「查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝 / 删除」

#### Scenario: 无草稿条目的禁用规则

- **WHEN** 某条目状态为 `analyzed`（判定不需要立项）
- **THEN** 「查看 SPEC 草稿」「同意」「拒绝」均禁用（置灰不可点），仅「查看分析结论」与「删除」可点

#### Scenario: 已决定条目的禁用规则

- **WHEN** 某条目状态为 `accepted`
- **THEN** 「同意」「拒绝」禁用，仍可查看分析结论与 SPEC 草稿（草稿已随接受删除时「查看 SPEC 草稿」按空态处理），且「删除」保持可用

#### Scenario: 同意需二次确认

- **WHEN** 用户点击「同意」
- **THEN** 先弹出确认弹窗；确认后才发起接受请求，取消则不发请求

#### Scenario: 删除需二次确认且明示重入库

- **WHEN** 用户点击「删除」
- **THEN** 先弹出确认弹窗，文案含「条目将从列表移除」与「todo.md 记录仍存在、可能在下一轮分析 run 中重新入库」；确认后才发起删除请求，取消则不发请求

### Requirement: 查看分析结论

「查看分析结论」MUST 在抽屉或弹窗中展示该条目的 `analysis_md` 全文（Markdown 渲染），内容来自 `GET /api/evolution/analysis?item_id=<id>`。加载中 MUST 有加载态；条目不存在 MUST 显示可读错误；结论缺失时 MUST 显示空态而非空白。

#### Scenario: 展示分析全文

- **WHEN** 用户点击某条目的「查看分析结论」
- **THEN** 面板展示该条目 `analysis_md` 全文（含三项判定与依据），先展示加载态，加载完成后替换为内容

#### Scenario: 条目不存在时报错

- **WHEN** 请求 `item_id` 不在 `.fenix/evolution/items.jsonl` 中
- **THEN** 接口返回 404，前端展示可读错误，MUST NOT 展示空白弹窗

### Requirement: 查看 SPEC 草稿

「查看 SPEC 草稿」MUST 展示该条目草稿的文档内容，来源 `GET /api/evolution/draft?item_id=<id>&doc=<proposal|design|tasks|spec>`；`doc` 超出白名单 MUST 返回 400；条目不存在返回 404；条目存在但草稿不存在（或已被接受删除）返回 `found: false` 并由前端显示空态。

#### Scenario: 切换查看四类草稿文档

- **WHEN** 用户对某 `pending` 条目点击「查看 SPEC 草稿」
- **THEN** 可查看 `proposal` / `design` / `tasks` / `spec` 四类文档内容，切换时不报错

#### Scenario: 非法 doc 被拒

- **WHEN** 请求 `doc=readme`
- **THEN** 返回 400，且 MUST NOT 读取草稿目录之外的任何文件

#### Scenario: 草稿已删除的空态

- **WHEN** 条目草稿已随接受流程删除
- **THEN** 返回 `found: false`，前端显示空态文案

### Requirement: 自己接受与拒绝的前端交互

「同意」成功后 MUST 刷新表格并提示「已立项：<spec_name>」；「拒绝」成功后 MUST 刷新表格并提示成功；两者失败时 MUST 展示后端错误文案、保持条目状态不变（以刷新后的真实状态为准）。

接受成功后的条目在表格中 MUST 显示为「已同意」，并在刷新前不可被重复提交（请求在途时按钮 MUST 禁用或忽略重复点击）。

#### Scenario: 同意成功刷新与提示

- **WHEN** 用户确认「同意」且后端返回成功
- **THEN** 表格被刷新，该条目显示「已同意」，并出现含新 SPEC 名的成功提示

#### Scenario: 拒绝成功刷新与提示

- **WHEN** 用户确认「拒绝」且后端返回成功
- **THEN** 表格被刷新，该条目显示「已拒绝」，并出现成功提示

#### Scenario: 失败不改状态

- **WHEN** 接受或拒绝请求返回错误（如提交失败、条目状态不允许）
- **THEN** 展示后端错误文案，表格刷新后仍显示真实状态，MUST NOT 出现「假成功」状态

### Requirement: 自进化 API 契约

Dashboard 后端 MUST 提供以下端点（沿用既有 `/api/*` 路由分发与错误语义）：

| 端点 | 方法 | 参数 | 语义 |
|------|------|------|------|
| `/api/evolution/items` | GET | 可选 `project` | 返回全部（或指定项目的）建议改进项摘要列表，按入库时间倒序 |
| `/api/evolution/analysis` | GET | `item_id` | 返回该条目 `analysis_md` 原文 `{found, content}`；条目不存在 404 |
| `/api/evolution/draft` | GET | `item_id`, `doc` | 返回草稿文档 `{found, content}`；`doc` 非白名单 400，条目不存在 404，草稿缺失 200 + `found: false` |
| `/api/evolution/accept` | POST | body `{item_id}` | 执行接受路径，成功返回新 SPEC 名与状态 |
| `/api/evolution/reject` | POST | body `{item_id}` | 执行拒绝路径，成功返回新状态 |
| `/api/evolution/delete` | POST | body `{item_id}` | 删除条目（硬删：记录移出 `items.jsonl` 并清理其草稿目录），不设状态门 |

参数缺失 / 非法 MUST 返回 400 且不触碰任何文件；`item_id` 未知 MUST 返回 404。端点 MUST NOT 接受任意文件路径参数（读取范围固定为 `.fenix/evolution/` 下由条目 id 推导出的路径）。每个条目摘要 MUST 至少含 `id`、`project`、`date_section`、`section`、`title`、三项判定、`status`、`has_draft`、`spec_name`、`created_at`、`decided_at`。

#### Scenario: 列表端点返回摘要字段

- **WHEN** 请求 `GET /api/evolution/items`
- **THEN** 返回 200，每条含 `id`/`project`/`date_section`/`section`/`title`/判定三项/`status`/`has_draft`，且按入库时间倒序

#### Scenario: 未知条目返回 404

- **WHEN** 请求 `item_id=nonexistent` 的分析或草稿端点
- **THEN** 返回 404 与可读错误，不读取任何文件

#### Scenario: 拒绝任意路径参数

- **WHEN** 请求携带 `path=/etc/passwd` 之类的任意路径参数
- **THEN** 该参数被忽略，读取范围仍限于由 `item_id` 推导出的 `.fenix/evolution/` 路径

#### Scenario: 删除端点移除记录与草稿

- **WHEN** 对某条目请求 `POST /api/evolution/delete`
- **THEN** 返回 200 + `{ok: true}`，该条目不再出现在 `GET /api/evolution/items` 结果中，其草稿目录被一并清理；缺参返回 400，未知条目返回 404
