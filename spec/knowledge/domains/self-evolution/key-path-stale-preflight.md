# 关键路径执行前陈旧代码预检

<!-- knowledge: capability=key-path-stale-preflight rev=1
     sources=spec/archive/2026-10-30-evo-add-key-path-stale-code-preflight -->

daemon 代码热装载依赖「磁盘代码比进程新 + 连续空闲」的陈旧自愈，夜间落地高峰会把空闲窗挤到数小时后——关键路径动作在此窗口内全部按旧代码执行。本能力让三个关键路径在执行前探陈旧、借 supervisor 通道加速重启，把修复装载延迟从小时级压到分钟级。

## 规则

- **陈旧旗标共享查询**：daemon 每 30 秒重算的代码陈旧旗标（进程启动 mtime 基线 vs 磁盘当前，`_code_stale`）经 `core/code_stale_flag.py` 模块级只读注册表暴露给 core 关键路径模块——注册表落 core 侧（daemon 启动初始化与每 30 秒检测点写入，core 读取），MUST NOT 出现 core 反向 import daemon；线程安全（daemon 检测线程写、车道线程读），查询本身零 IO；未注册（单元测试、独立脚本、冷启动窗口）时 fail-open 返回「不陈旧」，不抛异常。
- **三个关键路径预检**：动作执行前查询陈旧旗标，不陈旧时行为与无预检完全一致（零新增日志、零新文件写入）——① verification-report 收尾提交（engine.py 收尾步内 `_commit_verification_report` 调用点之前）；② 知识蒸馏批次派发（收敛在 `DistillManager.dispatch` 单汇聚点，单条/批量入口均经此单点、各恰产生一次告警与一次防重确保，MUST NOT 在单条与汇聚点两处重复插桩）；③ admin 车道处置 choice 执行（`execute_adjudication_choice` 调用之前）。
- **预检语义（照常完成 + 异步重启）**：陈旧时按序——记一条 WARNING（含陈旧状态与已请求重启的事实）→ 确保 `.fenix/restart_request` 存在（已存在则不重复写、不刷 mtime）→ 当前关键路径动作照常完成，不被预检阻塞或中断（返回值与产物和不变时一致）。重启经 supervisor 既有通道异步进行（每 2 秒轮询 restart_request）；重启打断在飞动作可接受——verification-report 文件先落盘后提交可重放、蒸馏派发有 pending 台账由重启后 recover_pending 接管。
- **restart_request 路径锚点**：解析为 daemon 自身仓库的 `.fenix/restart_request`（与 supervisor 的 `RESTART_REQUEST` 同一文件），MUST NOT 按 project_root 相对解析——治理第三方项目时 supervisor 只读 daemon 侧该文件。
- **与既有机制划界**：不改变陈旧自愈既有触发逻辑（空闲阈值触发、悬空超时强转、告警分级均不动）；不做代码热装载（不引入运行中 reload）。

## 溯源

- 2026-10-30 evo-add-key-path-stale-code-preflight（spec/archive/2026-10-30-evo-add-key-path-stale-code-preflight） — 新增本能力：陈旧旗标 core 侧共享注册表（fail-open）与三关键路径预检（verification-report 收尾/蒸馏派发/admin choice）、restart_request 防重与 daemon 侧路径锚点（动因实测：修复合并到代码装载时差 2 小时 16 分窗内 5 对收尾双提交 + 蒸馏批次被旧代码击杀）
