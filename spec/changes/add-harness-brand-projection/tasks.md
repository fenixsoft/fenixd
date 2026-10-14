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
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/tests/harnessBrand.test.mjs
  kind: new
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_run_metrics_persistence.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 品牌投影层

- [x] 1.1 新建 claude-msg/HarnessBrand.tsx：`HarnessBrandValue { name: string; Logo: ComponentType<{className?: string}> }` + context（缺省 `{ name: 'Claude', Logo: ClaudeLogo }`）+ `useHarnessBrand()` + `HarnessBrandProvider`；注册表含 dsh 品牌映射，未知值回退首字母徽标（内联小组件，不依赖图标资产）
- [x] 1.2 新建 claude-msg/DshLogo.tsx：官方鲸鱼 SVG **内联**为组件（源：本 change assets/dsh-mark.svg，即 deepseek.com/harness/favicon.svg），aria-label="dsh"；内联时**固化基础品牌蓝 #4D6BFE、移除源资产的 prefers-color-scheme 两条媒体查询**（应用固定浅色主题，OS 暗色偏好的白变体在浅底同色消失）；不落独立 .svg 资产文件
- [x] 1.3 MessageItem.tsx 去 字面耦合：headerLabelFor 与头像改经 useHarnessBrand()（错误/工具/系统等非 agent 消息的既有标签语义不变）；组件内不再出现字面 'Claude' 与无条件 ClaudeLogo

## 2. 真相源与后端透出

- [x] 2.1 runner 的 _log_run_metrics 结构化行增 `"harness": <该 run 派发时确定的 adapter.name>`——派发装配时记入 run 自身上下文、收尾从中取值，MUST NOT 收尾时读进程级 get_current_adapter()（`_current_adapter` 进程级全局以最后一次注入为准，并发 run 收尾会串号）；claude 通道即 "claude"，一次性 one_shot 车道同口径；adapter 未装配的提前终态路径（如排队期取消）省略该键
- [x] 2.2 dashboard/data/runs.py 索引 run_metrics 时把 harness 透出到 run meta（缺省 claude）；后端测试覆盖有值/缺省两形态（落点锚：tests/test_run_metrics_persistence.py 覆盖写侧形态、tests/test_dashboard_data.py 覆盖读侧透出）

## 3. 注入点

- [x] 3.1 RunRecordModal.tsx：新增 harness prop（两 Modal 现仅持 runId/project、不持有 meta），projects/detail.tsx 调用点从 runs 列表行 meta 取 harness 传入；Modal 内包 HarnessBrandProvider 注入对话 pane
- [x] 3.2 AdminRunModal.tsx 同口径注入：新增 harness prop，activities/index.tsx 调用点传入（admin 车道 run 的 meta 经 run_activity 同口径携带 harness，缺失时走回退链）
- [x] 3.3 SessionPanel 不注入（claude 专用豁免，缺省品牌即正确）——确认其渲染路径未被 1.3 破坏

## 4. 测试与收尾

- [x] 4.1 node --test（core/dashboard/static/tests/harnessBrand.test.mjs）：缺省=claude、dsh 映射、未知值回退徽标三分支
- [x] 4.2 前端构建（npm run build）+ 冒烟：浅色界面下 dsh 图标可见（品牌蓝单态；再以 prefers-color-scheme:dark 仿真复核不消失——媒体查询已移除应恒为品牌蓝）、claude run 显示不变
- [x] 4.3 回归：现有 node --test 全绿；python 侧 runs.py/runner 相关测试全绿

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-harness-brand-projection/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论：**无失败场景可核，打回无效**——verification-report.md 不存在，fail_history.json 第 1 轮 failed_scenarios=[]，daemon 日志证实验证链从未实际执行：场景 planner 3 次 + 旧版 verifier 3 次全部启动即挂（`/tmp/fenix-dsh-model-*.yml` 缺失的基础设施秒挂，daemon 重启窗口），「原地打回」系把验证链基础设施失败误判为验证失败，非产品/场景断言失败）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（复核结论为空失败集 → 无场景缺陷、无产品 Bug，产品代码与场景文件均无需修改；worktree 内交付物完整性已逐项核对——13 项声明交付物齐备，HarnessBrand/DshLogo/MessageItem/双 Modal/runner/runs.py 关键结构抽检与 SPEC 一致）
- [x] 修复后重跑验证确认通过（run 内重跑全绿：node --test 238 pass/0 fail（含 harnessBrand.test.mjs 三分支）、python 定向回归 test_run_metrics_persistence+test_dashboard_data 176 passed、test_agent_runner+harness adapter 107 passed、npm run build 成功且 dist 冒烟 #4D6BFE 在包、无 prefers-color-scheme 媒体查询；场景级验证由框架验证链在本 run 合并后独立重跑）
