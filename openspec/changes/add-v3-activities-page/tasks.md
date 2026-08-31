# Tasks: add-v3-activities-page

## 1. 数据层与页面骨架

- [x] 1.1 `src/services/dashboard.ts` 新增 `getAdminActivities(project?: string)` 封装
- [x] 1.2 `/activities` 路由替换占位页为真实页面：标题"运维记录"+ 页签栏（全部 + 各项目，Badge 条数）
- [x] 1.3 页签选中状态 state 化（跨刷新保持）+ 项目消失回退"全部"逻辑

## 2. 记录展示

- [x] 2.1 "全部"视图：按项目分段展示，段标题含项目名与条数
- [x] 2.2 单项目视图：仅展示该项目记录
- [x] 2.3 记录卡片（Timeline/Card 组合）：项目、时间、摘要等 v1 activityCard 元信息映射
- [x] 2.4 未处理升级置顶 + 高亮（danger/warning 视觉）
- [x] 2.5 空态："暂无运维记录"（Empty）

## 3. 实时与验证

- [x] 3.1 SSE `alerts`/`refresh` 事件静默重拉（保持页签与滚动），卸载关闭连接
- [x] 3.2 浏览器走查全部 spec Scenario；对照 v1 运维记录页核对字段映射
- [x] 3.3 console 零错误；`npm run build` 通过；dist 提交

## 验证修复（第 1 轮失败）

- [ ] 阅读 `openspec/changes/add-v3-activities-page/verification-report.md`，定位「真实产品 Bug」并修复
- [ ] 修复后重跑验证确认通过
