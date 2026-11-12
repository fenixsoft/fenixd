# 场景静态缺陷扫描
<!-- knowledge: capability=scenario-static-defect-scan rev=3 sources=spec/archive/2026-09-15-add-scenario-defect-triage-gate,spec/archive/2026-10-27-evo-add-verify-fixture-flag-guard,spec/changes/add-arbiter-blacklist-disposition -->

场景执行前的模式表驱动静态扫描：纯 Python 零 token 检出「结构合法但内容必败」与「会误伤共享生产账本」的已知缺陷模式，产出结构化情报供 judge 定向修复。只做情报、不拦截执行。

## 规则

- 扫描时机：每轮验证的场景执行前（`_apply_scenario_freeze` 完成后）对生效场景集（test_scenarios.json）执行静态缺陷扫描。
- 模式表驱动：扫描器以可扩展的模式表驱动（新增模式不改扫描器主体），当前模式包含——
  - 跨轮字面端口残留（cli/api）：steps `command`/`stdin` 文本中的字面端口号 ≠ 本轮 serving 实例端口 → 报「运行时必须引用 `FENIX_VERIFY_PORT` / `FENIX_VERIFY_BASE_URL` 环境变量」；端口一致时不产出 finding（不报脆弱绑定类低价值情报）。
  - 跨轮 navigate URL 残留（web）：`navigate` 步骤 URL 字面端口 ≠ 本轮 serving 端口 → 报「执行时引擎以契约 base_url 为准，但该场景入口指向已失效端口」。
  - 双汉字文本选择器（web）：steps `target` 或断言中恰好 2 个汉字的文本匹配 → 报「antd Button autoInsertSpace 将双汉字文本渲染为『X X』，建议改用 getByRole(name) 或含空格变体」。
  - 场景夹具注册未打标（cli）：steps `command`/`stdin` 文本（str/list 双形态拼接后扫描）中的 `add_project(` 调用实参未含字面 `fixture=True`（显式 `fixture=False` 与缺省不传均命中，变量传参等非字面写法漏报）→ 报「验证场景自注册探针夹具 MUST `fixture=True`（ADR-163），请补打标」；该模式与端口无关。规则本体与守卫层级边界见 test-engineering 域 [fixture-project-governance](../test-engineering/fixture-project-governance.md)。
- 生产副作用规则族（与既有规则同构表驱动挂载，规则族总计 9 条；实现验证场景环境耦合红线的机械子集）：
  - R1 改状态 click×位置选择器交叉判别（high）：click 目标含 `.first`/`nth()` 或缺 `:has-text` 种子/fixture 作用域锚定，且场景描述或后续断言表明该 click 改变生产账本状态；R1 依赖 click×expect_network 同场景关联的场景级交叉视图，规则函数签名向后兼容扩展（默认参数）。
  - R2 网络守卫过宽（medium）：改状态 click 的 expect_network 守卫仅锚端点前缀，未收敛到可区分本次操作的记录级路径。
  - R3 批量破坏端点确认路径执行（critical）：点击目标指向确认弹窗破坏性主键且场景含批量端点 expect_network（如 `POST /api/alerts/clear`、mark_all_handled 类）。
  - R4 全局聚合量绝对值断言（medium）：text_match 对全局聚合计数元素（如 `.ant-badge-count`）断言 exact/contains 具体数值；regex 形态断言不命中。
  - R5 `<tag>:text-matches` 组件按钮锚定（medium）：CSS 标签前缀+`:text-matches` 伪类组合命中最小元素语义结构性失配（与双汉字规则同源不同形）；容器作用域裸 `:text-matches` 不命中。
  - 规则族命中仅情报输出（fail-open 既有语义不变），注入 judge prompt；既有 4 规则行为零变化；安全作用域写法（种子行锚定+记录级守卫+形态断言）不误报。
- 回扫 CLI 入口：`python3 -m core.verify_engine.scenario_static_check --scan <场景集目录>` 对任意 test_scenarios.json 集合执行全规则族扫描，输出逐场景×逐规则×严重度的 findings 汇总，只读不改写；供编写期修复与启用前误报审计。
- 守卫 fixtures 双向锚定：复刻真实事故形态的 fixtures（位置点击按钮、种子作用域改写版、批量破坏确认、聚合量绝对值、`<tag>:text-matches` 组合）以 python 字面量内嵌守卫测试（不落 fixture 文件，避免场景文件形态双源），违规样本逐规则命中、合规样本全规则零命中。
- finding 结构：每条含 `scenario_id`、`rule_id`、`location`（场景内定位）、`message`（缺陷说明与修复方向）。
- findings 落盘与情报注入：findings 结构化落盘 `.fenix/verify-progress/<spec>/scenario_static_findings.json`（每轮覆盖写），并在 judge（planner-judge）prompt 构建时注入定向情报段——段内声明检出场景的缺陷修复属 judge 职责（原地修复协议、申报 scenario-repaired），judge 对已检出场景必须先修复已知缺陷再裁决；findings 为空时不注入该段。
- fail-open 扫描边界：静态扫描属辅助情报，扫描器任何异常（场景文件读取失败、模式匹配异常等）记 WARNING 后跳过本轮扫描，不阻断验证流程、不产生 error 终态；serving 端口未知的轮次，端口比对类模式整体跳过（双汉字、夹具打标等纯文本模式仍可执行）。

## 溯源

- 2026-09-15 add-scenario-defect-triage-gate（spec/archive/2026-09-15-add-scenario-defect-triage-gate） — 新增场景执行前的模式表静态扫描（跨轮端口残留/双汉字文本选择器）、findings 落盘与 judge 情报注入、fail-open 边界（此前场景跨轮环境假设随 replan 写回带进新一轮，seed 未建成导致下游场景连锁失败）
- 2026-10-27 evo-add-verify-fixture-flag-guard（spec/archive/2026-10-27-evo-add-verify-fixture-flag-guard） — 模式表新增 `unmarked_fixture_add_project`（cli 场景命令内 `add_project(` 未带 `fixture=True` 产出 judge 情报，`need_port=False`，只情报不拦截）
- 2026-11-12 add-arbiter-blacklist-disposition（spec/changes/add-arbiter-blacklist-disposition/） — 新增生产副作用规则族 R1–R5（位置点击改状态/网络守卫过宽/批量破坏确认/聚合量绝对值/组件按钮 text-matches 锚定）与事故形态 fixtures 双向锚定、存量场景集回扫 CLI 入口（`--scan` 只读汇总）；既有 4 规则与 fail-open 情报语义零变化
