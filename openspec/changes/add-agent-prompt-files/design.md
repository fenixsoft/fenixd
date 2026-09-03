## Context

现状盘点：六类 agent prompt 全部为 prompt_builder.py 内 f-string（1015 行）；`agents/` 目录已有 implementer.md / verifier.md / fast-track.md 三个手写角色 md 但无任何代码读取（文档残留，内容与现行 prompt 已脱节）；硬编码问题清单见 proposal（AMIS 死段、verifier 面板清单、领域规范误入）。设置页已有用户级/项目级分层模式（add-hierarchical-config 归档能力）与多页签结构（settings/index.tsx tabs）。

关键约束：`.fenix` 在 fenixd 自身项目是自引用符号链接（.fenix → 框架根），项目级 `.fenix/agents/` 与通用层 `agents/` 在该项目上重合。

## Goals / Non-Goals

- Goals：提示词文件化为唯一真相；项目级用户可设置（UI）；死知识删除、领域知识迁出框架；自引用边界安全
- Non-Goals：administrator 运维手册段落内容改写；planner prompt 按需瘦身；档案条目元数据/失效审计机制

## Decisions

### D1 文件为唯一真相、占位符替换、动态段仍归代码
六类 prompt 主体迁入 agents/*.md（以 prompt_builder 现行为为准重写，不沿用已脱节的手写 md 内容），路径类变量用 `{spec_name}`/`{spec_dir}`/`{scenarios_path}`/`{result_path}`/`{report_path}`/`{progress_path}` 占位符，加载时 `str.replace` 填充（不用 str.format——prompt 正文含大量 `{}` JSON 示例）。条件动态段（REPLAN/断点/error/遗产/冻结/契约/复核/verdict）保持代码生成、按状态追加——文件只承载静态主体。**不保留内置副本**：文件缺失派发报错，避免双真相漂移。

### D2 项目级附加：缺席零注入、位置固定在末尾
`.fenix/agents/<agent-type>.md` 存在则读入并以「## 项目附加提示词」标题附加在 prompt 完整内容（通用主体 + 动态段）之后——附加在末尾保证不影响通用指令的注意力权重结构。框架代码路径不写该目录；唯一下写入口是 Dashboard API 的用户保存动作。

### D3 领域知识迁移目标：被管项目而非框架
COS e2e、壳路由、seed 键格式的适用对象是被管产品（fenix-desktop），迁入该项目 `.fenix/agents/verifier.md`（与 planner 相关段入 planner-plan.md）；项目根以多项目注册信息定位，不可定位则 run result findings 登记转人工。AMIS 段无迁移价值直接删。

### D4 自引用项目禁用项目级编辑
fenixd 自身项目的 `.fenix/agents/` 即框架 `agents/`（自引用符号链接），若开放项目级编辑等于绕过「通用提示词不可修改」。设置页在该项目禁用编辑并显示原因；API 层同样拒绝（检测 project_root 与框架根解析为同一路径）。

### D5 UI 双视图复用分层配置模式
「提示词」页签（key: prompts）内按现有用户级/项目级切换结构组织：用户级=六文件只读展示（agent 切换）；项目级=通用只读 + 附加可编辑（TextArea 多行，按 agent 切换保存）。API：用户级只读端点 + 项目级读写端点（写入前 schema 无需校验——自由 Markdown，但路径限定 agent-type 白名单防目录穿越）。

## Risks

- **迁移时动态段与文件主体边界划错**：占位符只覆盖路径类变量，任何含条件逻辑的内容留在代码——实现时逐段核对 prompt_builder 现行分支
- **agents/*.md 为入库文件，被管项目无法改通用层**：属设计意图（通用=框架演进，走 SPEC）；被管项目定制走项目级
- **fast-track 一次做完六文件迁移 + UI**：回归面大，靠 4.2 全量回归与死关键词断言兜底；若实现超预算，优先保 prompt 链路正确、UI 可后置为 findings
