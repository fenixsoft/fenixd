# 能力：key-path-stale-preflight（关键路径执行前陈旧代码预检）

## 需求

### R1 陈旧旗标共享查询

- daemon 侧已有的代码陈旧判定（进程启动 mtime 基线 vs 磁盘当前，每 30 秒重算的 _code_stale 旗标，fenixd.py:1359）必须以模块级只读查询的形式暴露给 core/ 各关键路径模块；
- 注册表必须落在 core/ 侧（daemon 启动与检测点写入，core 模块读取），不得出现 core 反向 import daemon；
- 未注册（单元测试、非 daemon 语境、冷启动窗口）时查询必须 fail-open 返回「不陈旧」。

### R2 关键路径执行前预检

- 以下三个关键路径入口执行前查询陈旧旗标：
  - a) verification-report 收尾提交（报告入库的 git commit 执行前，core/pm_engine/engine.py 收尾步 → core/verify_report.py 的 _commit_verification_report）；
  - b) 知识蒸馏批次派发（core/knowledge.py 的 dispatch / dispatch_distill 入队前）；
  - c) admin 车道处置 choice 执行（core/admin_monitor.py 的 _apply_choice_execution 调 execute_adjudication_choice 前）。
- 查询结果为陈旧时，须按序：记一条 WARNING（含陈旧状态与已请求重启的事实）→ 确保 .fenix/restart_request 存在（已存在则不重复写）→ 当前关键路径动作照常完成，不被预检阻塞或中断。

### R3 防重与无副作用

- restart_request 已存在时不得重复写入或刷写其 mtime（与既有自愈「restart_request 已在，重启在途，不重复写入」语义一致）；
- 预检本身不得产生其他副作用：不写额外状态、不改变关键路径动作的返回值与产物。

## 验收标准

1. 陈旧旗标置位时，三个关键路径各自在执行前产生一条 WARNING 日志并确保 restart_request 存在；动作本身结果与不预检时一致。
2. 旗标未置位或注册表未注册时，关键路径行为与现状一致（无新增日志、无新文件写入）。
3. restart_request 已存在时，预检不重复写文件、不刷新 mtime。
4. 现有陈旧自愈测试（tests/test_stale_code_selfheal.py）全量不回归。
