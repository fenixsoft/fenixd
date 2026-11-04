# 知识真相源消费打通与形态整合设计

日期：2026-11-03
状态：brainstorm 定稿，待转 fenix-new 立项

## 意图与动机

知识蒸馏车道自 10-03 起持续产出能力页与 ADR，但本次取证发现知识体系存在五个缺陷，
根子是「三个池子互不相通」：

| 池子 | 规模 | 实际可用者 |
| --- | --- | --- |
| `spec/knowledge/`（显性，仓内） | 851 个 md（535 能力页 + ~300 ADR + 域导航） | 无人——全仓零消费 |
| auto-memory（隐性，仓外） | `~/.claude/projects/-root-fenixd/memory/` 250 文件 / 1.2MB | 仅 Claude Code 交互会话 |
| daemon 车道 agent（干活主力） | — | 什么都拿不到，每次从零搜库 |

五缺陷与取证事实（已核实，builder 无需重查）：

1. **蒸馏 agent 运作形式不一致**：四个知识车道 prompt（`distill/audit/backfill/prehistoric`）
   放在 `core/knowledge_prompts/`，游离于 `agents/` 之外；`agents/` 下 13 个车道 prompt
   由 `core/agent_runner/prompt_builder.py` 统一加载（「agents/ 是 prompt 唯一真相」）。
2. **隐性知识人类不可见**：auto-memory 是 Claude Code 产品级机制，按 cwd slug 键控。
   dsh 等其他 harness 根本不知道该目录；即使 Claude Code harness 的 daemon 车道也跑在
   worktree 里（cwd 不同 → slug 不同 → memory 为空）。memory 实际上只对
   `/root/fenixd` 下打开的交互会话可见。
3. **与 LLMWiki 格式的差距**：对照 Karpathy llm-wiki 模式（2026-04 gist），fenixd 已有
   wiki 层（域→能力→页 + marker 机器接口）与 Lint 操作（knowledge_audit）、
   Ingest 操作（distill，主输入 SPEC push 终态）+ 归档链接重写；缺的是
   **index-first 的消费路径**（`index.md` 仅 44 行域级导航，无人被指路去走）、
   **log.md 编年账**、**Query 回填**（会话结论回流知识库）。
4. **消费为零**：`agents/*.md` 全部 13 个提示词 grep 不到 `spec/knowledge` 任何指路；
   prompt_builder 无知识注入；交互会话的 `CLAUDE.md`/`AGENTS.md`/skills 也不指路。
   蒸馏产物唯一读者是 dashboard 人类视角和知识车道自身（自产自销闭环）。
5. **索引与同步不足**：三跳下钻链（`index.md` → `domains/<域>/_domain.md` → 能力页）
   结构上已存在但无人走；`index.md` 域级简介偏薄，agent 判断「任务涉及哪个域」信息量
   不足；memory→wiki 无任何回流管道。

## 目标

- **G1 消费打通**：daemon 车道与交互会话都有指路纪律，「接任务先查知识索引、下钻相关
  域与能力页」成为提示词层契约。
- **G2 回填管道**：交互会话产出的排查/立项结论有一条仓内路径回流 `spec/knowledge/`，
  由 daemon 车道按契约折叠进正式能力页。
- **G3 形态归位**：知识车道 prompt 纳入 `agents/` 统一管理；蒸馏产物补 LLMWiki 的
  `log.md` 编年账；`index.md` 域级简介增厚。
- **G4 定位澄清**：auto-memory 明确降级为「Claude Code 交互会话的私人草稿层」，
  项目知识真相只认仓内 `spec/knowledge/`。
- **G5 存量消化**：既有 250 个 memory 文件中仍然成立的项目级洞见渐进折叠进真相源。

## 非目标

- 不做向量检索 / embedding RAG / 语义搜索基础设施。
- 不做派发时动态知识注入（prompt_builder 不按任务挑页塞上下文）。
- 不迁移、不改写 auto-memory 目录本身（harness 机制保持原样，daemon 代码不读取它）。
- 不改变 distill 的主输入源（SPEC push 终态触发蒸馏的现有机制不动）。
- 不改 knowledge_audit 既有 lint 规则语义（只处理扫描范围与 `_inbox` 的关系）。

## 反目标（出现即算失败）

- 纪律行导致每次接任务 token 开销失控——index 必须保持精瘦，下钻深度由 agent 按任务自判。
- `_inbox/` 成为「无消费者的堆积区」——折叠消费者确定存在（distill 每轮顺带消化）；
  安静周（无 SPEC push 终态）积压滞留数周是**用户定调的设计内行为**（piggyback-only），
  以 audit 提醒兜底可见性，不算失败。
- knowledge_audit 对 `_inbox/` 误报契约违规（候选区本就豁免能力页契约）。
- 折叠产物破坏能力页 marker 契约或 150 行硬顶（knowledge audit 链接门已有前科，
  折叠必须过实时 `validate_knowledge`）。

## 约束

- `agents/` 是 prompt 唯一真相（`prompt_builder.agent_prompt_path` 加载 + 缺失即抛错），
  知识车道 prompt 迁入后加载路径代码必须同步。
- 能力页契约：H1 + marker（`capability`/`rev`/`sources`）+ 150 行硬顶 + 溯源段；
  distill 铁律「sources 路径逐一真实存在」是机器检查项（`core/knowledge.py` 校验）。
- 纪律行是静态文本，走 `agents/*.md` 修改即可，不新增 prompt_builder 代码路径。
- 全链时间戳 UTC；SPEC 驱动开发，本设计转 fenix-new 立项，交付验收以 Scenario 为准。

构建者检查（2026-11-03）已证实的底盘事实，builder 可直接依赖：

- `spec/knowledge/` 851 个文件全部 git 跟踪，worktree 车道可直接读取（G1 三跳下钻
  在 worktree 内可行，无分发问题）。
- distill 车道主树直跑（非 worktree），折叠可直接看到交互会话投递的 `_inbox/`，
  无时滞。
- self-review / code-fix 等独立构建车道同样经 `_load_agent_template` 加载
  `agents/*.md`，静态纪律行对所有拟覆盖车道统一生效，零新代码路径。
- `knowledge_audit` / `validate_knowledge` 的扫描范围仅覆盖 `index.md` + `domains/`
  （不含 `adr/` 全量链接检查），`_inbox/` 天然在体外，仍须测试钉死。
- `rewrite_source_links_to_archive`（`core/knowledge.py:670`）当前对
  `spec/knowledge/` 下**全部** `*.md` 做归档路径改写——新增 `log.md` 与 `_inbox/`
  必须显式豁免（见 SPEC B 交付物）。

## 用户已定决策

- **D1 消费形式 = 静态纪律行**。知识量太大，派发注入不可行；由 `agents/*.md` 纪律行 +
  index-first 三跳下钻承担，深浅 agent 自判。
- **D2 memory 归宿 = 交互会话私人草稿层**。它锁 harness、锁 cwd、锁机器，不配作知识
  底座；值得沉淀的洞见必须经回填管道进仓。
- **D3 回填管道 = 仓内候选区**。交互会话把结论投递到 `spec/knowledge/_inbox/`
  （自由格式，只求讲清楚不求守契约），daemon 车道折叠进正式能力页——LLMWiki 的
  「raw sources → wiki」两层结构，契约执行收敛到 daemon 一处。
- **D4 范围 = 形态与消费都做**，五缺陷全覆盖。
- **D5 存量消化不入 SPEC B 验收**（2026-11-03 用户定调）：B 只交付回填管道；250 个
  memory 文件的价值预筛与分批投递是管道落地后的交互会话渐进活动，进度挂 `todo.txt`
  台账防静默烂尾，不设机械终态判据。
- **D6 折叠触发 = piggyback-only**（2026-11-03 用户定调）：`_inbox` 非空**不**构成
  独立派发条件，不新增 fold-only run 形态；折叠只搭 distill 车道每轮的便车，
  安静周滞留由 audit 提醒兜底。

## 交付物蓝图

### SPEC A：知识消费纪律与索引增厚（内容层，无 daemon 代码改动）

- `agents/` 各消费车道 prompt 增加知识纪律段（拟覆盖：`planner-plan`、`implementer`、
  `code-fix`、`administrator`、`self-review`、`arbiter`；具体车道清单 builder 可按
  「该车道是否做需要背景知识的判断/排查」增删，在 SPEC 里列全并说明理由）。
- 纪律行基准文案（分车道微调措辞，语义保持）：
  > 接任务后先读 `spec/knowledge/index.md`（44 行域级索引），判断本任务涉及哪些能力域；
  > 命中相关域则 MUST 下钻该域 `domains/<域>/_domain.md` 与相关能力页后再动手；
  > 未命中可跳过，不得为走流程而全量阅读。
- 力度定为「条件 MUST」：读 index 是硬纪律（44 行成本低），下钻以命中为条件。
- **作用域**：`agents/` 是框架级文件，纪律行对 daemon 全部项目生效；文案带存在性
  条件——项目尚无 `spec/knowledge/` 时静默跳过，不引入项目级配置键
  （与「fenixd 不做项目级特殊处理」「新配置键须配 Dashboard 界面」两条既有纪律相抵）。
- 项目 `CLAUDE.md` 与 fenix-new / fenix-process 等 skill 同步加同款指路（交互会话
  与立项动作共享同一消费纪律）；并注明「值得沉淀的结论投递 `spec/knowledge/_inbox/`」
  的回填纪律（该目录由 SPEC B 创建，CLAUDE.md 文案先行不碍事）。
- `spec/knowledge/index.md` 域级简介增厚：每域简介从一句话扩为反映能力面的 2~3 句
  （素材取各域 `_domain.md` 能力清单），更新时间戳刷新。
- 验收 Scenario（示例，立项时可细化）：
  - Scenario：implementer 接到涉及已蒸馏能力的任务 → prompt 含纪律段 →
    run 转录中出现读取 `spec/knowledge/index.md` 与相关能力页的 Read 调用。
  - Scenario：任务与任何域无关 → agent 读完 index 即继续，无域页阅读，无告警。
  - Scenario：无 `spec/knowledge/` 目录的项目（fenixd 管辖的其他项目）→ 纪律行
    存在性条件静默跳过，无报错、无常驻开销、无配置项。

### SPEC B：候选区回填管道与蒸馏形态归位（daemon 代码层）

- **`spec/knowledge/_inbox/` 候选区**：交互会话投递自由格式 markdown
  （文件名建议 `YYYY-MM-DD-<topic>.md`，含背景/结论/证据三段即可，不守能力页契约）。
  现状 `knowledge.py` 的 lint 扫描仅遍历 `domains/` 与 `adr/`，`_inbox` 天然在体外，
  但须用测试钉死该豁免，防未来扫描范围变更时误伤。
- **折叠消费者（piggyback-only，D6）**：distill 车道每轮（现触发点：SPEC push 终态）
  先消化 `_inbox/` 存量，再处理当轮 SPEC 蒸馏；`_inbox` 非空不构成独立派发条件，
  不新增 fold-only run 形态。audit 周期轮对 `_inbox` 积压做提醒：**不走 AdminStore
  人工告警**（遵循人工告警降噪偏好），落 `log.md` lint 行 + dashboard KnowledgeTab
  展示积压计数；提醒阈值＝积压 ≥10 条或最老条目滞留 ≥7 天，随周期轮幂等去重。
- **折叠动作**：按能力页契约把候选内容折叠进相关能力页（或新建能力页），遵守 150 行
  硬顶与溯源段规范；折叠前跑实时 `validate_knowledge`，失败不得落盘。
- **marker sources 契约扩展**（本 SPEC 关键设计点，需裁决）：
  - 现契约 sources 仅接受 `spec/changes/<SPEC名>` 且机器校验路径真实存在。
  - 折叠来源的规则需要新 sources 形态，推荐方案 **(a)**：折叠成功后候选条目移入
    `spec/knowledge/_inbox/done/` 保留（LLMWiki raw source 不灭的精神），
    marker sources 允许指向 `_inbox/done/<文件名>`，机器校验放行该前缀。
  - 备选 (b)：折叠规则走免 sources 白名单形态。选 (a)，理由：溯源机器可校验、
    候选原文永久可考。
- **`spec/knowledge/log.md` 编年账**：追加式，行前缀
  `## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`（操作 ∈ distill/fold/backfill/lint），
  时间基准随真相源人类可读惯例走本地时区显式标注（2026-11-03 裁决：不接受同目录
  两套时间惯例并存；运行时链路仍全链 UTC 不变）；日期前缀保持 unix 工具可 grep；
  distill/audit 每轮收尾追加。
- **归档改写豁免**：`rewrite_source_links_to_archive` 显式排除 `log.md` 与
  `_inbox/**`（含 `done/`），测试钉死——候选原文逐字节冻结，接受其中指向已消失
  `spec/changes/` 路径的历史形态文本（「候选原文永久可考」承诺的落地）。
- **蒸馏 prompt 归位**：`core/knowledge_prompts/{distill,audit,backfill,prehistoric}.md`
  迁入 `agents/`（迁移形态——平铺还是 `agents/knowledge/` 子目录、加载代码怎么改——
  builder 定，但必须保持「agents/ 是 prompt 唯一真相」不破例）；迁移后删除旧目录，
  grep 全仓清引用。
- **存量消化（管道外渐进活动，不入 B 验收，D5）**：管道落地后由交互会话对 250 个
  memory 文件做价值预筛（剔除 harness 专属/用户偏好/已蒸馏条目），分批投递
  `_inbox/`（不做全量机械拷贝），由折叠机制渐进消化；进度挂 `todo.txt` 台账防静默
  烂尾；memory 原件不动。SPEC B 的 Scenario 用合成夹具验证管道即可，不依赖存量投递。
- 验收 Scenario（示例）：
  - Scenario：`_inbox/` 有 1 条候选 → distill 轮结束 → 相关能力页规则段出现折叠内容、
    marker sources 含 `_inbox/done/` 路径且机器校验通过、候选条目已移 `done/`、
    `log.md` 追加 fold 行。
  - Scenario：候选内容使目标能力页超 150 行 → distill 拆页（主从分片互链）而非放行。
  - Scenario：`_inbox/` 有违规 markdown（烂格式）→ audit 轮不报契约违规，仅积压提醒。
  - Scenario：知识车道 prompt 从 `agents/` 新路径加载成功，`core/knowledge_prompts/`
    不复存在，全仓 grep 无残留引用。
  - Scenario：归档迁出触发 `rewrite_source_links_to_archive` → 能力页/ADR 照常改写，
    `log.md` 与 `_inbox/**`（含 `done/`）逐字节不变。

## 留给 builder 的部分

- 纪律行的分车道措辞与最终车道清单；`prompt_builder` 对 `agents/` 子目录的加载实现。
- distill 折叠的具体挂点（车道入口序、与既有「队列台账单写者」ADR-234 的兼容）。
- `log.md` 追加的并发安全（distill 与 audit 轮是否会并发写）。
- `_inbox/done/` 目录结构、折叠失败条目的重试/滞留策略。
- SPEC 拆分微调：A 与 B 相互独立可并行，但 B 的 CLAUDE.md 回填纪律文案依赖 A 先行
  （建议 A 先立项，B depends_on A 或错峰）。

已定死、builder 无需再议的边界：折叠触发 piggyback-only（不做 fold-only 派发改造，
D6）；积压提醒不发人工告警、阈值 ≥10 条或滞留 ≥7 天；归档改写豁免
`log.md` 与 `_inbox/**`；`log.md` 时间基准本地时区 `UTC+8` 显式标注；纪律行全局生效
带存在性条件、无项目级配置键；存量消化不入 B 验收（D5）。

## 交付后定位声明（写进两 SPEC 的验收共识）

- 三个池子的终态：`spec/knowledge/` = 唯一项目知识真相源（全 harness 可达、人类可见）；
  auto-memory = 交互会话便利层（允许继续记录，但项目级结论必须投递 `_inbox/`）；
  daemon 车道 = 知识消费者（纪律行走三跳下钻）+ 回填执行者（折叠）。
