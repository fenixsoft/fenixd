# Tasks: fix-spawn-attribution-hardening

> 执行纪律：TDD（任务组 1 测试先行）；Linux 零变化硬约束；
> **任务组 2/3/6 属进程 API/服务承载面——过机复验必做不豁免**（design D6）。

## 1. pytest 先行（纯逻辑层覆盖）

- [x] 1.1 spawn 解析 helper：`shutil.which` mock——解析到 `.cmd` 时 argv[0] 被替换
  （win32 分支）、解析不到时返回 None（fail-fast 路径）；POSIX 分支断言 argv[0]
  保持裸名逐位不变；预检与 spawn 消费同一 helper
- [x] 1.2 infra-deterministic 分类：`FileNotFoundError(2)` → 终态、预算不变、
  不进重试队列；归因三型字段（spawn_failed/nonzero_exit/result_missing）
- [x] 1.3 `fenix_spec.py new` schema 前置：缺 `schemas/spec-driven/schema.yaml`
  时 exit 非 0 且不落 `.spec.yaml`（tmp_path 隔离）
- [x] 1.4 日志卫生：注释-only 配置 → DEBUG 级断言；getpgid 守卫（win32 mock）；
  ConnectionResetError 静音断言
- [x] 1.5 `install_unit(root, env=...)` 注册表 MultiString 形态（fake writer 断言
  元素列表）+ env_defect 自检逻辑（服务 PATH 解析失败 → env_defect 明细）

## 2. spawn 解析单源化（A3，过机面）

- [x] 2.1 claude_adapter spawn-spec 构建接入 which 解析 helper（argv[0] 替换）
- [x] 2.2 `precheck_harness_executable` 复用同一 helper（删独立 which 判定）
- [x] 2.3 Linux 回归：argv[0] 替换仅 win32 生效——Linux SpawnSpec 逐位不变
  （tests/test_harness_claude_snapshot.py 金样本零触碰全绿）

## 3. 失败分类与归因（A4，过机面）

- [x] 3.1 dispatch 层 FileNotFoundError(2/3) → infra-deterministic 终态
  （不消耗 impl_run_budget、不重试、不 arbiter），error 带修复指引
- [x] 3.2 归因三型分立 + result_missing 附 stderr 尾窗（截尾 2KB）

## 4. fenix_spec schema 前置（A1r）

- [x] 4.1 `new` 写盘前调 load_schema，缺失 fail-fast + 修复指引（§3A 口径文案）

## 5. 日志卫生（A5/A6）

- [x] 5.1 用户配置空对象 ERROR → DEBUG（消息保留路径）
- [x] 5.2 getpgid 平台守卫（core/proc_utils.py kill_process_group——全库
  os.getpgid 唯一调用点；v2 dev-server 停止链等消费方随之覆盖）
- [x] 5.3 dashboard ConnectionReset/Aborted 静音（core/dashboard/server.py
  DashboardHandler 覆写 handle_one_request，debug 单行；SSE 流路径已有同族捕获不重复动）
- [x] 5.4 全库 docstring r-string 机械批改 + 编译复核零警告（宿主 3.10 用
  `-W error::DeprecationWarning` 口径；≥3.12 解释器用 `-W error::SyntaxWarning`）

## 6. install_unit env 注入与服务环境自检（A7，过机面）

- [x] 6.1 `install_unit(root, env=None)`：注册表 `Parameters\AppEnvironmentExtra`
  MultiString 直写（原子多元素；read-modify-write 合并——同键 K=V 覆盖、异键保留，
  防整值替换清除 §8 手工 PATH 最小集）
- [x] 6.2 服务环境自检（幂等重跑 already=True 与安装完成两路径）：服务 PATH
  视角解析 claude/git/python，缺失 → 返回 JSON `env_defect` 明细（ok 仍 True）
- [x] 6.3 过机复验三件（design D6）：缺 PATH 一跳终态 / which→.cmd spawn 真链 /
  env 注入服务内可见 + env_defect 预警——记录进 windows-native-support 清单
  （2026-11-16 用户拍板：win-test 通道冻结不解，三件转用户侧人工验证担纲，
  登记为 G1 清单 G1-26~28，SKIP 附通道冻结证据）

## 7. verdict 收口

- [x] 7.1 宿主全量 0 failed 0 新增豁免（Linux 零变化；daemon 常驻宿主所致
  test_v2_dev_server 端口占用类环境性失败逐例归因记录，不计新豁免）
- [x] 7.2 过机复验三件全过（任务 6.3）+ 清单执行记录回填
  （2026-11-16 用户人工验证担纲收口；G1-26~28 执行记录已登记，通道冻结证据 win-test-channel-freeze.md）
- [x] 7.3 提交：SPEC 目录 + 实现分开提交，message 引用本 SPEC 名
