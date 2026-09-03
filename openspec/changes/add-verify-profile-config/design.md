## Context

四类 agent prompt 中盘点的硬编码清单（prompt_builder.py，共 1015 行）：

| 位置 | 内容 | 定性 |
|---|---|---|
| planner-plan 210-218 | 云端 COS e2e（腾讯云、同步键、解锁下载） | 项目特定（被管产品） |
| planner-plan 223-241 | AMIS/dark- 选择器大全 | 已死（v2 已删，v3 栈为 antd v6） |
| planner-plan 242-244 | 壳路由 href（app.json、#/config） | 项目特定 |
| planner-plan 280-283 | seed 键 fenix:sync:persisted-key 例子 | 半项目特定（原则通用） |
| verifier 110-117 | Step 3 MANDATORY 面板清单（Stock sh600036/Notes/Calculator/Email） | 项目特定且以强制口吻误导 verifier |
| planner-judge 421 | `.dark-Card` 归因示例 | 已死 |
| _interaction_contract_section 936 | `dark-Card--link` covers 示例 | 已死（注入 implementer/planner） |
| administrator 619-628 | fenixd dashboard 运维手册（8787/tmux） | 框架自身事实，**范围外不动** |

注入机制现状：全部为 f-string 常量拼接；动态段（scenario freeze、interaction contract、triage recheck）已有按状态注入的先例可复用其模式。

## Goals/Non-Goals

- Goals：项目事实外置为用户可设置档案；死知识删除；迁移知识不丢失；验证页签可编辑
- Non-Goals：administrator prompt（框架自身事实，另行治理）；planner prompt 整体瘦身/按需规范注入（另行 SPEC）；模型环境事实（"不支持图像输入"）的配置化

## Decisions

### D1 存储与 schema：verify.yaml 扩展 profile 键
复用既有声明式契约文件 `.fenix/verify.yaml`（load_verify_contract 已是解析入口），新增 `profile:` 顶层键 = 条目列表（id/agents/text）。不新建文件——验证知识集中一处，且被管项目的 verify.yaml 机制天然支持每项目独立档案。`agents` 取值 planner/verifier/fast-track；planner-plan 与 planner-judge 都按 planner 匹配（避免用户理解两个 planner id）。

### D2 注入：过滤 + 单标题段
prompt_builder 构建四类 agent prompt 时读取档案，`agents` 命中则拼入「## 项目验证档案（用户配置）」段（置于动态段之前）。**无命中 → 不加任何字节**——保证既有测试与 prompt 快照零漂移。档案内容为用户自担的领域知识，框架不校验其正确性，只做 schema 结构校验（id 唯一、agents 取值合法）。

### D3 死知识直接删、项目知识迁档案
AMIS 大全与 dark- 示例无迁移价值（组件库已删）直接删；COS/壳路由/seed 三段迁入 fenixd 自身 `.fenix/verify.yaml` 作为初始档案条目。verifier Step 3 改写为通用表述（"点击遍历被测应用每个主要界面/面板，每次交互必须有可见结果，否则为 BLOCKING BUG"——保留其防僵尸 UI 的意图，去掉产品面板名）。

### D4 UI：验证页签内嵌条目编辑器
设置页 verify 页签新增「项目验证档案」区块（antd v6，对齐现有页签实现模式）：条目列表（id 输入、agents 多选 Checkbox、text 多行 TextArea）+ 新增/删除 + 保存按钮。API 走 dashboard server 既有 verify.yaml 读写路径（若无则新增 GET/PUT profile 端点）。保存即落盘；prompt 注入在下次派发生效，无需重启。**v3 dist 改动后必须重建并提交**（验证假阴性教训）。

## Risks

- **档案成为新的"只增不减"堆场**：条目自带 id 便于定位清理；页签可见性高于代码 f-string（用户看得见就更容易删）；本 spec 不建自动失效机制（另行治理）
- **fast-track prompt 结构与 planner/verifier 不同**：注入位置需在 fast-track 的验证阶段指引附近，任务中单独验证
- **verify.yaml 手工编辑与 UI 并发写**：沿用 verify.yaml 既有读写方式，UI 保存为整文件写回（当前项目级低频编辑，不做合并）
