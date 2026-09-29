# 帮助文档集（docs/help/）

<!-- knowledge: capability=help-docs rev=1
     sources=spec/archive/2026-09-10-add-dashboard-help-center -->

框架仓库 `docs/help/` 下面向人类读者的中文使用文档集：以当前代码为唯一事实来源，系统讲解完整开发流程、状态机、CLI、验证体系、治理规则与故障排查。

## 规则

- 文档集构成：`docs/help/` 由「`README.md` 目录索引 + 按两位编号命名、按编号排序的中文正文章节」组成；每篇正文有唯一一级标题且非空；README 含指向全部正文的相对链接，并给出「新用户入门」与「运维排查」两条阅读路径。具体章节清单以目录现状为准，保障机制专章的契约由 `docs-safeguards-chapter` 能力页承载。
- 覆盖范围（按主题域考核，不随章号漂移）：完整开发流程（安装→初始化→启动→提需求→自动循环→审批推送）落入快速上手与核心概念；状态机全部状态与合法转移（含 blocked→ready 人工恢复、verified→done、pushed 终态、门禁逃生门与冻结机制）落入生命周期篇；fenix-* skill 与 bin/ 辅助脚本、fast-track 与 full 模式选择标准落入 CLI 篇；三步验证流水线、verify.yaml 契约、场景冻结、verdict 分类与修复循环落入验证篇；优先级/并发/三类预算/重试退避/超时监督/自动恢复/merge 熔断/fix 族谱收敛/告警分级/重启协议落入治理篇（每条规则配「对用户意味着什么」说明）；Dashboard 与帮助页用法落入 Dashboard 篇；分级配置合并、热更新与全部配置键落入配置篇；STATE.md、SPEC artifacts、Deliverables 声明段、runs/verify-progress/admin_alerts/todo.md/PROJECT_LOG.md 落入数据地图篇；故障现象→根因→处置落入 FAQ 篇。
- 图表纪律：文档中所有示意图（架构、流程、状态转移、时序）一律以 `mermaid` 围栏代码块承载，禁止 ASCII 字符画；架构图（核心概念）、端到端流程图（快速上手）、stateDiagram-v2 状态图（生命周期）、验证流水线图（验证篇）、告警分级流向图（治理篇）五类必备图必须在场。
- 以代码为准：文档描述的行为以当前代码实现为准；README.md 或 config.template.yaml 与代码缺省不一致的点按实际行为书写，并在配置篇集中设「模板值与代码缺省不一致」小节逐条澄清，结论为「实际生效值以项目 config.yaml 为准」。
- 可读性与交叉引用：每篇文档不依赖阅读顺序即可理解（首次出现的术语给一句话解释或指向术语表）；相关主题之间用相对链接交叉引用（如治理篇→配置篇的具体键、FAQ→数据地图篇的排查文件）；抽取任一篇全部相对链接，目标文件必须存在于 `docs/help/` 且锚点指向的标题真实存在。

## 溯源

- [2026-09-10 2026-09-10-add-dashboard-help-center](spec/archive/2026-09-10-add-dashboard-help-center/) — 建立文档集与撰写契约：README+编号章节结构、主题覆盖清单、mermaid 图表纪律、以代码为准与模板漂移点集中澄清、每篇独立可读与交叉链接有效性
