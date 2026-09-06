## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
# dist 为前端构建产物（.gitignore dist/ 排除、不入 git，由框架重建），声明为
# reference 仅审计留痕，不参与守卫缺件硬校验——add-spec-hooks dist 守卫自伤
# 事故同型预防（2026-09-06，modify 声明在 git 对账下任何分支不可满足）。
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_spec_scheduling.py
  kind: new
- path: skills/fenix-new/SKILL.md
  kind: modify
```

## 1. 状态机层共享基础

- [x] 1.1 在 core/state_machine.py 新增模块级工具：`parse_utc(value)`（ISO8601 解析，非法返回 None）、`start_after_pending(entry, now) -> bool`（start_after 非空且晚于 now 返回 True，解析失败视为不阻塞）、冻结原因中原状态解析函数 `parse_orig_status(error) -> str`（匹配「原状态 X」，缺失回退 ready），附单元测试
- [x] 1.2 core/dashboard/data.py 的 freeze/unfreeze 改为委托 StateMachine.freeze_spec/unfreeze_spec（原状态并入冻结 reason；解冻 status 传解析出的原状态），消除「结构化冻结 spec 被 dashboard 解冻致 status 剥离」的半死态

## 2. 调度门控与到期检测（daemon 侧）

- [x] 2.1 core/pm_engine/dispatch.py 候选筛选处接入 start_after 门控：`start_after_pending` 为真时静默跳过（debug 日志，不写 error 不翻状态）
- [x] 2.2 core/pm_engine/engine.py `_on_spec_ready` 入口补 start_after 门控（防 boot recovery / 重派路径绕过），并核对全部派发入口均过谓词（含 recovery.py 路径），在代码注释登记核对结论
- [x] 2.3 core/pm_engine/engine.py 新增 `check_scheduling_deadlines()`：冻结 spec 的 frozen_until 到期 → 经 StateMachine.unfreeze_spec(status=parse_orig_status) 自动解冻（写前重读确认仍冻结，幂等）；非终态 spec 的 start_after 刚到期且 drafted/ready → 唤起 _on_spec_ready
- [x] 2.4 fenixd.py 主循环新增 60s 独立计时段调用 check_scheduling_deadlines（try/except 记日志不中断，对齐 recovery watch 模式）

## 3. Dashboard 后端 API

- [x] 3.1 core/dashboard/data.py 新增 start_after 读写纯函数（ISO8601 校验、非法拒绝、null 清除、终态拒绝），core/dashboard/server.py 增路由 `POST /api/spec-start-after`
- [x] 3.2 core/dashboard/data.py 新增冻结配置函数：mode=permanent 清 frozen_until / mode=scheduled 写 frozen_until（已过去立即解冻）/ mode=unfreeze 立即解冻；core/dashboard/server.py 增路由 `POST /api/spec-freeze-config`

## 4. Dashboard 前端

- [x] 4.1 core/dashboard/static/src/services/dashboard.ts 封装 setSpecStartAfter / setSpecFreezeConfig 两个 API
- [x] 4.2 core/dashboard/static/src/pages/projects/list.tsx 行菜单增「设置拾取时间」（非终态）：Modal 含本地时区 DatePicker 与清除定时按钮，提交转 UTC ISO
- [x] 4.3 list.tsx 对 start_after 未到期 spec 渲染定时 Tag（目标时间本地渲染 + 分钟级倒计时，随既有数据刷新节奏更新）
- [x] 4.4 list.tsx 冻结 spec 行菜单增「冻结管理」：Modal 展示当前模式（永久/定时+目标时间）与冻结原因，RadioGroup 切换永久/定时、DatePicker 设时间、立即解冻按钮；现有「冻结/解冻 Spec」菜单项行为不变
- [x] 4.5 dashboard 前端构建（dist 重建），确认中文文案与移动端 screen-xs 作用域无回归

## 5. fenix-new 流程更新

- [x] 5.1 更新项目源 skills/fenix-new/SKILL.md：新增 `--start-after` 参数约定（绝对时间按本地 UTC+8 解释、`+Nh`/`+Nm` 相对时长按提交时刻解释），注册时经 add_spec attrs 写入 start_after，未指定不写字段；同步安装副本 ~/.claude/skills/fenix-new/SKILL.md 保持两份一致（沿用 add-fast-track-mode 6.1/6.2 模式）

## 6. 测试与回归

- [x] 6.1 新增 tests/test_spec_scheduling.py：覆盖 start_after 门控（未到期跳过不写 STATE、到期拾取、非法格式拒绝、过去时间等价无限制）
- [x] 6.2 覆盖定时解冻：到期自动解冻恢复原状态并清 frozen_until、幂等竞争、daemon 重启后扫描兜底、设置过去时间立即解冻、时间轴含「定时解冻」来源标记
- [x] 6.3 回归覆盖冻结双轨：StateMachine.freeze_spec 冻结 → dashboard unfreeze → status 正确恢复（半死态消除）；dashboard freeze → daemon 感知停止调度
- [x] 6.4 全量测试跑通（tests/ 无新增失败），API 层用 test_dashboard_api.py 同款夹具方式覆盖两个新路由
