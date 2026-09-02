# Tasks: add-project-description

## 1. 配置存储与模板

- [ ] 1.1 `config.template.yaml` 增加注释示例字段 `description`（project 节下，注明由 fenix-setup 生成、可在 Dashboard 修改）
- [ ] 1.2 `core/dashboard/data.py` 的 `_deep_merge_managed` 增加 `description` 分支：patch 顶层 `description`（str）写入 `merged["project"]["description"]`，保留 project 节其它键

## 2. 后端读取与展示数据

- [ ] 2.1 `read_effective_config` 增加提取分支：`effective["project"]["description"]` → 结果顶层 `description`（非 str 或缺失 → ""）
- [ ] 2.2 `project_summary`（data.py）增加 `description` 字段，取项目 config `project.description`，缺失为空串；确认 /api/projects 与 /api/overview 均携带

## 3. AI 重新生成接口

- [ ] 3.1 `server.py` 新增 POST `/api/project/describe?project=<name>`：读项目根 README.md（≤8KB 截断，缺失时改读 package.json/pyproject.toml 前 4KB）拼固定中文指令 prompt，`subprocess.run(["claude","-p",prompt], cwd=项目根, timeout=120, shell=False)`；成功经 `write_config` 落盘返回 `{ok, description}`；非零退出/超时/空输出返回 `{error}` 且不改 config
- [ ] 3.2 为 describe 接口添加测试：prompt 组装与截断、成功路径 mock subprocess、失败路径（超时/非零退出）不改写 config

## 4. 前端设置页面板

- [ ] 4.1 `settings/index.tsx`：`MENU_ITEMS` 改运行时构造，scope 为项目级时末尾追加 `{key:'project-profile', label:<项目名>}`，用户级不出现；ConfigData 类型补 `description?: string`
- [ ] 4.2 新建 `settings/components/ProjectProfilePanel.tsx`：TextArea 回显 config.description + 保存（走既有 handleSave，patch `{description}`）+「AI 重新生成」按钮（调新接口，loading 态，成功刷新 config、失败 message.error 保留原值）；空值占位「暂无简介」
- [ ] 4.3 `services/dashboard.ts` 增加 `regenerateProjectDescription(project)` API 封装

## 5. 前端项目列表展示

- [ ] 5.1 概览页 ProjectCards：项目名称下以 Paragraph ellipsis 单行展示 description，空值占位「暂无简介」
- [ ] 5.2 项目列表页（projects list）同样展示 description，空值占位

## 6. fenix-setup skill 步骤

- [ ] 6.1 `skills/fenix-setup/SKILL.md` 新增简介生成步骤：读 README.md（缺失看 package.json/pyproject.toml/目录结构）生成约 100 字中文简介写入 `.fenix/config.yaml` `project.description`（文件存在则就地合并该键）；信息不足或任何异常时写默认文案「由 Fenix 框架管理的项目，暂无自动生成的简介。」并继续后续步骤，不阻塞 daemon 启动

## 7. 验证

- [ ] 7.1 后端测试全绿：`python3 -m pytest tests/ -q`（含新增 describe 接口测试与 write/read_config description 分支用例）
- [ ] 7.2 前端构建产物同步（v3 dist）并浏览器验证：项目级作用域出现项目同名页签、用户级不出现；编辑保存生效；AI 重新生成成功与失败路径表现符合 spec；PC 端设置页与移动端横排菜单零回归
- [ ] 7.3 端到端验证 fixture 项目：config 写入 description 后 /api/overview、/api/projects、项目卡片与列表展示链路完整（参照 Dashboard fixture 验证配方，不烧 token）
