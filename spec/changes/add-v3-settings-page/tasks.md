# Tasks: add-v3-settings-page

## 1. 数据层与页面骨架

- [x] 1.1 `src/services/dashboard.ts` 新增 `getConfig(project?: string)` 与 `saveConfig(project, payload)` 封装（GET/PUT `/api/config`）
- [x] 1.2 `/settings` 路由替换 `PagePlaceholder` 为真实设置页骨架：左侧 inline 菜单（六子项）+ 右侧面板区，默认选中 LLM Provider
- [x] 1.3 作用域切换：头部用户级/项目级选择（URL query 持久化），切换时重新拉取配置
- [x] 1.4 `GET /api/config` 接入：表单填充、`raw_exists=false` 提示、`sources` 继承标注展示

## 2. 六个设置子项

- [x] 2.1 LLM Provider：Provider 卡片列表（Form.List + Input.Password），新增/编辑/删除/保存写回 `llm.providers`
- [x] 2.2 Agent 模型分配：按角色 Select Provider + model 输入，写回 `agents.models`；providers 为空时展示引导提示
- [x] 2.3 并行度设置：max_concurrent / max_turns / run_timeout_seconds 三个 InputNumber（含 v1 同款说明文案）
- [x] 2.4 审批模式：approve_mode Radio.Group（manual/auto + 说明文案）
- [x] 2.5 Token 预算：token_budget_millions / daily_run_limit / impl_run_budget 三个 InputNumber（含范围校验）
- [x] 2.6 界面风格：亮/暗切换，写 localStorage `fenix.theme` + ConfigProvider 主题切换，不进入保存路径

## 3. 保存与反馈

- [x] 3.1 统一保存逻辑：当前子项变更 merge 到最近 GET 数据后 PUT 全量受管键，成功提示 + 静默重拉
- [x] 3.2 失败反馈：展示后端 error 信息，表单保留用户输入
- [x] 3.3 数值范围校验（InputNumber min/max + Form rules），校验失败不发起 PUT

## 4. 验证

- [x] 4.1 浏览器走查全部 spec Scenario（布局/切换/六子项读写/继承标注/主题持久化/错误反馈）
- [x] 4.2 与 v1 配置页交叉核对：同一项目在 v1 与 v3 读取的键值一致，v3 保存后 v1 读取可见
- [x] 4.3 console 零错误；`npm run build` 通过；dist 提交## 验证修复（第 2 轮失败）

- [x] 阅读 `openspec/changes/add-v3-settings-page/verification-report.md`，定位「真实产品 Bug」并修复
- [x] 修复后重跑验证确认通过
