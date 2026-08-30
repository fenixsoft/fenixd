# Tasks: add-verify-scenario-freeze

实现依据（实施 agent 必读）：
- 能力定义 `specs/verify-scenario-freeze/spec.md`；设计决策 design.md D1-D4
- planner prompt 与场景输出解析：`.fenix/core/agent_runner.py`（planner-plan / planner-judge prompt 构建处）
- 修复轮判定信号：`_verify_fail_rounds`（STATE.md 内部字段）与 tasks.md「## 验证修复」段
- 场景产物目录：`.fenix/verify-progress/<spec>/`

## 1. 场景集持久化

- [ ] 1.1 新增 `.fenix/core/verify_scenarios.py`：读写 `.fenix/verify-progress/<spec>/scenarios.json`（scenario_id + description + 来源轮次），含原子写
- [ ] 1.2 首轮验证裁决后将产出场景集写入（已存在文件时走 diff 流程而非覆盖）

## 2. 修复轮约束

- [ ] 2.1 修复轮判定（D1 信号）接入 planner-plan/judge prompt 构建：注入持久化集与「仅新增范围可追加、删减须理由」约束
- [ ] 2.2 新增确定性 diff 校验器：planner 产出 vs 持久化集——缺既有场景且无理由 → 以持久化集补齐并在报告标注；追加场景合并写回（记录轮次）
- [ ] 2.3 验证报告新增「本轮场景集变更」小节（新增/移除及理由）

## 3. 单元测试

- [ ] 3.1 覆盖：首轮写入；修复轮不扩容（planner 超发被拦）；新增范围合法追加写回；无理由删减被补齐并标注；报告变更小节渲染
- [ ] 3.2 用 v2-config-page 真实 11→17 场景数据作夹具回归（17 场景中仅 11 个可保留 + 修复段未声明新增 → 收敛回 11）

## 4. 验证与打包

- [ ] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [ ] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包
