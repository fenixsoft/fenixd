# 知识真相源
> 最后更新：2026-11-10 14:54 UTC+8

本项目知识按**能力域**组织：域内一能力一页，只装当前生效的业务规则；
历史演变见各页「溯源」段与 `spec/archive/`。能力页由存量回填批次逐步产出，
各域导航页先行登记能力条目（能力页落盘后升级为链接）。

## 能力域

> 分组与编号为**纯导航层展示**：域 slug、目录名与机器接口不变；组归属由蒸馏 run 维护，重组须用户定调。

### 1 项目与规格（4 域 · 43 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 1.1 | [project-management](domains/project-management/_domain.md) | 项目的发现接入、描述信息与生命周期控制（daemon 启停 systemctl 双轨/软删除）。含项目初始化骨架播种与针对 SPEC 的冻结/删除停止语义。 | 8 | 2026-11-08 19:28 |
| 1.2 | [planning-generation](domains/planning-generation/_domain.md) | SPEC 的原生生成链路：从需求澄清到 proposal/design/tasks 成文。planner 出题阶段的产物硬门、契约情报与性能治理同属此域。 | 6 | 2026-10-03 04:59 |
| 1.3 | [ui-prototyping](domains/ui-prototyping/_domain.md) | 界面原型确认环：SPEC 起草阶段用「真组件、假数据」的高保真原型对齐界面意图，浏览器批注迭代至批准入库。批准后以双通道契约约束后续 AI 实现与评审（原型纯视觉参照、无约束力），原型控制台 vendor DEV 警告非缺陷判读。 | 3 | 2026-11-10 14:28 |
| 1.4 | [spec-lifecycle](domains/spec-lifecycle/_domain.md) | SPEC 全生命周期：起草评审门（spec-review）与驳回恢复、晋升（含中文标题晋升硬门）/手工激活/定时解冻调度、并发治理与内容完整性门。归档链（手工/自动归档、归档态迁移与自动提交）与 fast-track 模式选择、状态机模型、立项与成文定调、SPEC 中文标题（display name）也在此域。 | 26 | 2026-11-10 12:24 |

### 2 执行车道（6 域 · 171 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 2.1 | [dispatch-scheduling](domains/dispatch-scheduling/_domain.md) | SPEC 并发槽位与优先级调度、队列老化、依赖唤醒与兜底恢复。即时唤醒信号与事件投递完整性、秒挂冷却派发门控、派发前置 harness 可达性自检与 PATH 自愈也在此域。 | 10 | 2026-11-08 21:21 |
| 2.2 | [implementer-lane](domains/implementer-lane/_domain.md) | 实现车道的任务协议与交付物门禁：tasks.md 进度同步/回写、验收偏差申报、结果文件契约与自检、回归委托。交付物声明与归属仲裁（声明分诊/争议治理/搬迁回写）、WIP 检查点与任务产物归属也在此域。 | 28 | 2026-11-04 17:07 |
| 2.3 | [verify-pipeline](domains/verify-pipeline/_domain.md) | 验证管线全链：runner 引擎与场景生命周期、验证环境预检与依赖供给、serve 范围矩阵与实例回收。场景冻结/打捞/schema 单源、多形态场景模型（web/cli/api）与资源互斥。验证报告门、裁决证据留存、视觉基线与并行回退等质检机制同属此域。 | 60 | 2026-11-10 11:20 |
| 2.4 | [verdict-adjudication](domains/verdict-adjudication/_domain.md) | 验证裁决与证据：裁决产物的产生与门检、证据分类与归因可信度、裁决结果与失败语义。查重与重合成、缓存复验、env 类失败的豁免握手与场景修订处置出口也在此域。裁决在 Dashboard 的可见性与结果文件兜底读取同属此域。 | 28 | 2026-11-08 00:40 |
| 2.5 | [code-review-lane](domains/code-review-lane/_domain.md) | 周期性代码审查车道：注册/调度（夜间静默窗跨窗顺延）、scope 两档、分片直写落盘、进度聚合与停滞看门狗。审查发现台账与质量分面（快照核销/三态分派）、发现转修复 SPEC 生成、全仓审查并发约束与限流终局续跑。实现期收尾 ocr 审查（异步车道 + join 门）及其配置调优。 | 19 | 2026-11-04 16:55 |
| 2.6 | [code-fix-lane](domains/code-fix-lane/_domain.md) | 缺陷修复车道：两路激活与批循环编排、批内并行处置、批收尾回归门与失败明细映射。回归异常熔断与零失败面收口、修复批自愈重试预算分档。合回冲突定向救回、夜间静默窗投递守卫与审查发现分级修复节奏同在此域。 | 27 | 2026-11-08 00:40 |

### 3 运行时与守护（6 域 · 117 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 3.1 | [agent-runtime](domains/agent-runtime/_domain.md) | Agent 进程托管与信号处理、非交互运行契约、提示词文件化。run 产物留存、超时与轮次上限生命周期、提示词层效率治理。 | 17 | 2026-11-04 17:07 |
| 3.2 | [harness-integration](domains/harness-integration/_domain.md) | 多 harness 接入：以进程边界为唯一接缝（SpawnSpec 进、归一化事件出），把「换 harness」收窄为「实现 adapter + 部署注册」。HarnessAdapter 协议与 claude 字节级平移、fenix-dsh Bundle 与 DshAdapter 事件投影、切换治理、dsh web 会话组织（分组判据/registry 写约束/归档 API 通道/会话流 append 闸）与 fenixd 侧会话自动卫生（确定性标题/run 终态多 attempt 全量归档）。run jsonl 以 claude stream-json 形状为唯一 canon；CLAUDE_PID watchdog 为显式豁免面。 | 8 | 2026-11-09 20:13 |
| 3.3 | [run-resilience](domains/run-resilience/_domain.md) | 运行守护与失败韧性：超时监督与挂死判别、失败分类与错误归因降噪、失败计数与预算分档。运行清扫、重派循环治理、诚实退出收敛、状态写原子性与幂等、孤儿态探测、CLI 重试退避与环境阻塞止损。arbiter 车道故障分级（infra/judgment）与前置自检复位也在此域。 | 31 | 2026-11-10 11:24 |
| 3.4 | [recovery-continuity](domains/recovery-continuity/_domain.md) | 中断恢复与续做：daemon 中断、停机与重启后的完整恢复链——现场保全、保留分支续做、存活核验、遗留处置。恢复监视告警、取消保持恢复与验证断点。 | 15 | 2026-11-09 18:04 |
| 3.5 | [daemon-runtime](domains/daemon-runtime/_domain.md) | daemon 进程生命周期、单例与托管链、启动序列与排水语义。托管链 systemd 承载层（unit 安装、on-failure 重启策略与 supervisor 退出码协议、EnvironmentFile 环境承载与捕获 PATH 卫生）同属此域。结构化日志单事件读写治理。宿主环境已知脆弱面登记。 | 17 | 2026-11-08 21:21 |
| 3.6 | [worktree-vc](domains/worktree-vc/_domain.md) | 实现工作树的隔离、播种、回读与卫生：spec 锁终态释放与陈锁清扫、已合并分支宽限期自动回收、分支基线解析单源口径、冻结 spec 清理豁免。实现分支合回主树与推送的全生命周期纪律（推送 git 子进程凭证双腿确定性、done 态退避周期扫描续推）；主树 WIP 占用归因单源、周期盘点与滞留升级、untracked 散件自动认领、白名单文件脱落巡检。 | 32 | 2026-11-09 17:58 |

### 4 模型与成本（2 域 · 35 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 4.1 | [provider-models](domains/provider-models/_domain.md) | LLM provider 注册表与角色模型分配（含快速分配）、候选链与 failover（dispatch 环与八条 LLM 车道）、瞬断治理与熔断。provider 引用校验与分配失效划界。计费配置、分级配置与设置界面的配置体系、Provider 手动健康检测。 | 21 | 2026-11-10 14:40 |
| 4.2 | [cost-observability](domains/cost-observability/_domain.md) | run 成本采集与本地计价、预算与费控治理。延迟/进度/耗时观测、run 记录流呈现可读性与产物保留策略。 | 14 | 2026-11-04 16:30 |

### 5 前端交互（3 域 · 69 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 5.1 | [dashboard-frontend](domains/dashboard-frontend/_domain.md) | 跨项目仪表盘前端。覆盖现产六页（概览/项目列表/SPEC 详情/配置/运维/帮助）与指挥中心的页面规则、全站统一标题栏与 chrome 染色、antd 表格与滚动纪律、移动端卡片流编排、SPEC 状态标签（含 blocked 处置相位三态）。另有 dsh 面板桥集成（嵌入挂载/工作区行项目导航/设置停靠）、dsh web 访问面（入口账号密码登录、连接基线、设置 UI 契约）、Bento 磁贴视觉条款（12px 圆角、跨域镜像不引用）与帮助文档体系。 | 45 | 2026-11-10 14:54 |
| 5.2 | [dashboard-platform](domains/dashboard-platform/_domain.md) | 跨项目 Web 仪表盘的服务端与平台层：独立服务进程、实例生命周期（双轨重启协议）、增量数据管线。按需生成类任务与指挥中心聚合同属此域。 | 16 | 2026-11-08 21:21 |
| 5.3 | [mobile-adaptation](domains/mobile-adaptation/_domain.md) | dashboard 前端在窄屏视口（<768px）下的适配规则：断点统一、信息密度、触控目标、渐进披露与越界布局优先。 | 8 | 2026-11-07 21:43 |

### 6 运维与自愈（2 域 · 52 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 6.1 | [admin-ops](domains/admin-ops/_domain.md) | Administrator 自愈 agent、健康监视与异常探测、处置留痕与运维记录视图、维护型工作登记台账。人工裁决选择题、告警生命周期与自解释叙事、告警面板验证夹具种子、请求型信号前置探测闭环、孤儿处置生效核查收敛。升级处置链（Admin→Arbiter→人工）的路由配额与链痕协调、链上处置台账即时闭合与 choice 链上执行、可观测配置、Arbiter 自主裁决车道。 | 35 | 2026-11-08 21:09 |
| 6.2 | [self-evolution](domains/self-evolution/_domain.md) | 每日定时自省与聚合口径、框架自进化车道（条目复核与 SPEC 起草立项）、产物契约校验与部分接受、架构师 agent。陈旧代码自愈及其冷却保护、关键路径陈旧预检、todo.md 写路径防护、arbiter 立项通道退役注记。 | 18 | 2026-11-04 17:07 |

### 7 工程与质量（4 域 · 22 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 7.1 | [test-engineering](domains/test-engineering/_domain.md) | 测试套件自身的结构、隔离与守卫。全量回归的声明、执行与展示。Docker 集成测试环境（一键编排、凭据注入与网络故障判别）也在此域。 | 15 | 2026-11-10 14:35 |
| 7.2 | [build-gates](domains/build-gates/_domain.md) | 仓库构建层面的前置把关：交叉编译检查等编译级门禁，在提交前与实现 run 收工自证前拦截构建类缺陷。 | 1 | 2026-10-12 08:31 |
| 7.3 | [codebase-structure](domains/codebase-structure/_domain.md) | core 后端代码的结构组织与结构类重构纪律：包分层、门面转发契约、巨型类与超长函数拆分。 | 4 | 2026-10-03 04:59 |
| 7.4 | [time-semantics](domains/time-semantics/_domain.md) | 全链时间语义：时间原语单源、时区分层约定（存储 aware UTC / 渲染本地）、naive 时间戳唯一解读策略。静态守卫防回潮与存量调用点迁移稳态。 | 2 | 2026-11-04 15:55 |

### 8 文档与知识（2 域 · 20 能力）

| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- | --- |
| 8.1 | [docs-help](domains/docs-help/_domain.md) | 面向人类的框架使用文档体系：`docs/help/` 文档集的内容契约。Dashboard 帮助中心功能与保障机制专章。 | 5 | 2026-11-07 21:43 |
| 8.2 | [knowledge-atlas](domains/knowledge-atlas/_domain.md) | 知识真相源（`spec/knowledge/`）子系统：目录契约（含代码锚点段与退役即删不墓碑）、归档蒸馏管线与 `_inbox/` 候选区回填管道、ADR 决策索引、项目知识页签与配置开关等机制能力。存量回填、周期体检、退役 runbook、Graphify 关系图等维护车道与 index-first 消费纪律；真相源只装当前生效业务规则，归档 SPEC 承担历史职责，两者以溯源链接互指。 | 15 | 2026-11-08 03:35 |


## 决策记录

- [ADR 索引](adr/index.md) — 跨 SPEC 架构级决策（编号、状态、一句话摘要）
