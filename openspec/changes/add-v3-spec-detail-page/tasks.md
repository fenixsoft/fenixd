# Tasks: add-v3-spec-detail-page

## 1. 路由、入口与常驻区

- [x] 1.1 `config/routes.ts` 增加 `/projects/:name/:spec` → `pages/projects/detail.tsx`；列表页名称列点击跳转
- [x] 1.2 `src/services/dashboard.ts` 新增 `getSpecDetail(project, spec)`（`/api/specs/<spec>?project=`）与运行流封装
- [x] 1.3 详情页骨架：头部（名称/状态/onBack）+ error 横幅 + 元信息（P/创建/更新/依赖）
- [x] 1.4 常驻区四区块：验证结论、验证进度、Token 用量（含"成本不可用"降级）、任务清单（分组 + 勾选状态）

## 2. 四个页签

- [x] 2.1 页签骨架：四页签恒可见，空态文案对齐 v1（场景结果区分 report 损坏 vs 无数据）
- [ ] 2.2 运行时间轴：Timeline 混排状态/运行节点（回退原因可见），antd Timeline 实现
- [ ] 2.3 运行对话流：RunStream 子组件（watch 尾部拉取 + SSE run_events 增量 + thinking 折叠 + 卸载清理）
- [ ] 2.4 场景结果：汇总 Tag 计数 + 场景卡片 + 失败断言/步骤明细
- [ ] 2.5 Bug 列表：卡片（severity/source/描述/关联场景/证据/缩略图）
- [ ] 2.6 失败截图：Image.PreviewGroup 缩略图 + lightbox（/screenshots/ 路径）

## 3. 验证

- [ ] 3.1 浏览器对照 v1 同 spec（如 fenixd/refactor-core-packages）逐区块走查内容一致
- [ ] 3.2 运行对话流实测：展开运行节点按需加载、增量追加、无连接泄漏（卸载关闭 SSE）
- [ ] 3.3 空 spec（无运行/无场景/无 bug/无截图）页签空态走查
- [ ] 3.4 console 零错误；`npm run build` 通过；dist 提交
