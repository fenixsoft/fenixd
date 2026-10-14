## Deliverables

```yaml
- path: core/dashboard/static/src/components/claude-msg/HarnessBrand.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-msg/DshLogo.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-msg/MessageItem.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/RunRecordModal.tsx
  kind: modify
- path: core/dashboard/static/src/pages/activities/components/AdminRunModal.tsx
  kind: modify
- path: core/dashboard/static/tests/harnessBrand.test.mjs
  kind: new
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 品牌投影层

- [ ] 1.1 新建 claude-msg/HarnessBrand.tsx：`HarnessBrandValue { name: string; Logo: ComponentType<{className?: string}> }` + context（缺省 `{ name: 'Claude', Logo: ClaudeLogo }`）+ `useHarnessBrand()` + `HarnessBrandProvider`；注册表含 dsh 品牌映射，未知值回退首字母徽标（内联小组件，不依赖图标资产）
- [ ] 1.2 新建 claude-msg/DshLogo.tsx：官方鲸鱼 SVG **内联**为组件（源：本 change assets/dsh-mark.svg，即 deepseek.com/harness/favicon.svg，保留其明暗自适应 style 块），aria-label="dsh"；不落独立 .svg 资产文件
- [ ] 1.3 MessageItem.tsx 去 字面耦合：headerLabelFor 与头像改经 useHarnessBrand()（错误/工具/系统等非 agent 消息的既有标签语义不变）；组件内不再出现字面 'Claude' 与无条件 ClaudeLogo

## 2. 真相源与后端透出

- [ ] 2.1 runner 的 _log_run_metrics 结构化行增 `"harness": <current adapter.name>`（claude 通道即 "claude"；一次性 one_shot 车道同口径）
- [ ] 2.2 dashboard/data/runs.py 索引 run_metrics 时把 harness 透出到 run meta（缺省 claude）；后端测试覆盖有值/缺省两形态

## 3. 注入点

- [ ] 3.1 RunRecordModal.tsx：从 run meta 读 harness，包 HarnessBrandProvider 注入对话 pane
- [ ] 3.2 AdminRunModal.tsx 同口径注入
- [ ] 3.3 SessionPanel 不注入（claude 专用豁免，缺省品牌即正确）——确认其渲染路径未被 1.3 破坏

## 4. 测试与收尾

- [ ] 4.1 node --test（core/dashboard/static/tests/harnessBrand.test.mjs）：缺省=claude、dsh 映射、未知值回退徽标三分支
- [ ] 4.2 前端构建（npm run build）+ 冒烟：亮/暗主题下 dsh 图标可见、claude run 显示不变
- [ ] 4.3 回归：现有 node --test 全绿；python 侧 runs.py/runner 相关测试全绿
