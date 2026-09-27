## Deliverables

```yaml
- path: spec/knowledge/README.md
  kind: new
- path: core/knowledge.py
  kind: new
- path: core/knowledge_prompts/distill.md
  kind: new
- path: core/dashboard/routes/knowledge_routes.py
  kind: new
- path: core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx
  kind: new
- path: core/archive_commit.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 配置项与目录骨架

- [ ] 1.1 core/config.py 新增 `knowledge` 段解析（`enabled` bool，缺省 true，非法值回退 true 并告警），config.template.yaml 登记带注释模板行；补设置回读单测
- [ ] 1.2 core/dashboard/static/src/pages/settings/index.tsx 设置页新增 `knowledge.enabled` 开关控件与说明文案（保存走既有配置 POST 链路，热更新生效），补渲染单测
- [ ] 1.3 新建 spec/knowledge/README.md：目录契约说明（域/能力/ADR 布局、marker 格式、150 行硬顶、溯源行格式），作为蒸馏 run 与人类读者的契约文档

## 2. 蒸馏管线核心（core/knowledge.py）

- [ ] 2.1 新建 core/knowledge.py：`validate_knowledge(project_root)` 确定性校验（marker 可解析、sources 指向存在的 spec/archive/ 目录、单页 ≤150 行、index/_domain/adr 链接可解析、ADR accepted 正文不可变 diff、Superseded by 指向存在条目）；`dispatch_distill(project_root, archived_name, config)` 派发入口（knowledge.enabled 门控）
- [ ] 2.2 新建 core/knowledge_prompts/distill.md 蒸馏提示词：目录契约与风格正反例（禁历史叙述措辞）、ADDED/MODIFIED/REMOVED 合并语义、ADR 跨 SPEC 架构级判据（含正反例、允许零产出）、supersede 只标不改、首跑自举分支（建骨架+自动聚类定域）、写路径限定 spec/knowledge/
- [ ] 2.3 core/archive_commit.py 在 commit_archive_move 移动成功分支追加 dispatch_distill 调用（fail-open：异常仅记日志与重试登记，不影响归档返回值与提交结果），补两条路径（手工/daemon）共同覆盖的单测
- [ ] 2.4 蒸馏 run 执行器：daemon 侧 spawn claude -p 后台 run（cwd 主树、注入 distill.md 提示词），run 结束后跑 validate_knowledge，违规回反馈修正（≤2 轮），通过后 pathspec 限定 spec/knowledge/ 的自动提交（commit 形如 `[fenix] knowledge: distill <归档名>`，fail-open 记 warning）；失败登 todo.md 重试条目；单测用 fake spawn 替身覆盖成功/校验失败两轮修正/放弃三支路

## 3. 后端只读 API

- [ ] 3.1 新建 core/dashboard/routes/knowledge_routes.py：`GET /api/knowledge/index`、`GET /api/knowledge/file`（path 白名单前缀 domains/ 与 adr/，越界与 `..` 恒 400）、`GET /api/knowledge/graph`（graph/graph.html 存在性探测，缺失 404）；未初始化（无 index.md）返回占位结构
- [ ] 3.2 core/dashboard/server.py 注册 knowledge 路由 Mixin，补路由冒烟单测（含路径穿越用例断言 400）

## 4. 前端「项目知识」页签

- [ ] 4.1 新建 core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx：active 门控按需拉取（选中才请求）、index.md Markdown 渲染与能力页点击导航、ADR 列表视图（状态标签 + superseded 跳转）、graph 区内嵌渲染位与「关系图尚未生成」占位、`knowledge.enabled` 为 false 时的禁用占位
- [ ] 4.2 core/dashboard/static/src/pages/projects/list.tsx 在「架构」与「会话接入」之间插入「项目知识」页签（label 与 key 遵循既有 ListTab 类型），补页签渲染单测
- [ ] 4.3 构建前端产物（npm build）并经 playwright（-s 命名会话、打 worktree 实例端口）冒烟：页签位置、按需加载（未选中无请求）、index 渲染、占位文案

## 5. 端到端与回归

- [ ] 5.1 e2e 测试（fake spawn 替身，不触真实网关）：构造 fixture change 归档 → 断言 dispatch_distill 被触发、蒸馏产出经校验落盘、index/域清单同步更新、REMOVED 语义删规则留痕、ADR supersede 链正确
- [ ] 5.2 全量回归通过（pytest 既有套件 + 本 SPEC 新增用例），dashboard 手工冒烟记录归档（worktree 实例）截图至 .history/
