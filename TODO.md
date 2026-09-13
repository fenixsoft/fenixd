# TODO List for fix-run-hang-amplification Implementation

## Status Tracking
- [x] 1. 挂起判别 (hang-discrimination)
  - [x] 1.1 分离计数实质事件/心跳
  - [x] 1.2 修正零事件守卫
  - [x] 1.3 新增常量
  - [x] 1.4 实现可观测零产出短路
  - [x] 1.5 后台调用输出文件追踪
  - [x] 1.6 修订 judge prompt
  - [x] 1.7 短路判定日志
  - [x] 1.8 负向约束验证
- [x] 2. 预算与诊断连续性 (run-budget-continuity)
  - [x] 2.1 细化豁免判据
  - [x] 2.2 更新调用点
  - [x] 2.3 新增结构化诊断字段
  - [x] 2.4 注入诊断到 prompt
  - [x] 2.5 保护诊断字段不被清除
- [x] 3. 有界套件入口 (baseline-blocked-gate)
  - [x] 3.1 新增 run_full_suite.py
  - [x] 3.2 --baseline 模式
  - [x] 3.3 契约引导更新
  - [x] 3.4 hooks 测试 skip
- [x] 4. 并发隔离 (concurrent-suite-isolation)
  - [x] 4.1 修复 find_free_port TOCTOU
  - [x] 4.2 环境变量端口段约定
  - [x] 4.3 主机级互斥
- [x] 5. 测试
  - [x] 5.1 挂起判别测试
  - [x] 5.2 零产出短路测试
  - [x] 5.3 负向约束测试
  - [x] 5.4 预算连续性测试
  - [x] 5.5 诊断注入测试
  - [x] 5.6 run_full_suite 测试
  - [x] 5.7 端口分配测试
  - [x] 5.8 hooks skip 测试
- [x] 6. 全量验证
  - [x] 6.1 全量回归
  - [x] 6.2 边界复核
  - [x] 6.3 导入收敛

## Progress Notes
- 开始时间: 2026-09-13
- 使用 worktree: /root/fenixd/.claude/worktrees/impl-fix-run-hang-amplification-1789284770
- 主树参考: /root/fenixd (只读)
- 已完成大部分核心实现，需要补充剩余测试和验证