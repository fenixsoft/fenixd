# Design: web-runner-assertion-eval-timing

## 现状与根因

core/verify_engine/web_runner.py:393-437 将断言批在全部 steps 执行完后统一求值（:435），trial click 亦延至断言批时刻（core/verify_engine/assertions.py:429）。导航类场景（如 wire-e2e 会话流、web-profile-custom-tier）中途经 show('session') 切换视图，交互断言求值时目标元素已不可见，not visible 走非遮挡分支且无视图证据——judge 只能逐场景补断言落点规避（现集 10/34 场景锚 #connect-btn），同类误报持续再生。

## 方案

- 求值计划分桶：web_runner 构建断言求值计划时按类型分桶——交互型断言（no_click_interception）绑定其目标步骤索引，在该步骤完成点求值（含 trial click）；流程级断言保持既有后置批。类型判定读断言声明，场景零改动。
- 视图快照归因：assertions 的 not visible 失败分支采集轻量 DOM 摘要（当前可见视图 id、目标元素所在视图、可见性判定依据），附入失败载荷；不上截图。

## 取舍

- 不做全量 per-step：流程级断言（no_console_error 等）语义横贯全程，per-step 求值会破坏其语义且放大开销——保持后置。
- 不纳入条目建议②（judge 修复轮批量修复断言落点）：属 judge 行为面而非 runner 结构面，且引擎侧修复后逐场景补丁需求自然消失。
- 交互断言绑定「步骤完成点」而非步骤中间态，避免步骤后续副作用未落时误判。