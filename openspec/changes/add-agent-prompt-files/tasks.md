## Deliverables

```yaml
- path: agents/implementer.md
  kind: modify
- path: agents/verifier.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: agents/planner-plan.md
  kind: new
- path: agents/planner-judge.md
  kind: new
- path: agents/administrator.md
  kind: new
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: new
```

## 1. 通用提示词文件化

- [ ] 1.1 六类 agent prompt 主体按 prompt_builder 现行为迁移到 agents/<agent-type>.md（implementer/verifier/fast-track 重写对齐现行 prompt，planner-plan/planner-judge/administrator 新建；路径变量改占位符 `{spec_name}`/`{spec_dir}`/`{scenarios_path}`/`{result_path}`/`{report_path}`/`{progress_path}`）
- [ ] 1.2 死知识清理：AMIS 选择器大全段删除；`.dark-Card`/`dark-Card--link` 示例改 data-testid 通用示例；verifier Step 3 面板清单（Stock/Notes/Calculator/Email/Quick Links）改通用表述（保留「交互必须有可见结果否则 BLOCKING BUG」）
- [ ] 1.3 prompt_builder 改为文件加载 + str.replace 占位符填充 + 动态段按状态追加；文件缺失显式报错（移除内置副本）；接入六类 agent 分支

## 2. 项目级附加机制

- [ ] 2.1 prompt_builder 读取 `<项目根>/.fenix/agents/<agent-type>.md`，存在则「## 项目附加提示词」附加在 prompt 末尾，缺席零注入
- [ ] 2.2 领域知识迁移：COS e2e/壳路由/seed 键格式写入对应被管项目 `.fenix/agents/verifier.md`（项目不可定位则 findings 登记）
- [ ] 2.3 自引用防护：项目根解析与框架根相同时，项目级读取跳过（该项目的项目级即通用层）

## 3. Dashboard「提示词」页签

- [ ] 3.1 server.py：用户级只读端点（agents/*.md 列表与内容）+ 项目级读写端点（.fenix/agents/，agent-type 白名单校验防目录穿越，自引用项目拒绝写）
- [ ] 3.2 settings/index.tsx 新增「提示词」页签：用户级六类只读切换展示；项目级通用只读 + 附加可编辑保存；自引用项目禁用编辑并提示原因
- [ ] 3.3 v3 dist 重建并提交

## 4. 测试与回归

- [ ] 4.1 tests/test_agent_prompt_files.py：覆盖 spec 全部 Scenario（占位符替换、动态段语义、缺失 fail-fast、项目级附加/缺席零注入、自引用防护、死关键词断言、端点读写与白名单校验）
- [ ] 4.2 既有测试全量回归（prompt 相关与派发链路）
