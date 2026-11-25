# Design: add-platform-abstraction-layer

## Context

架构真相源：`docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md`（已批准评估，2026-11-10）——§5 PAL 设计（六组 API A–F 面、单点分发、向后兼容策略）、§7 SPEC 分解（本 SPEC = W1–W7）、§8 风险登记。知识依据：`spec/knowledge/_inbox/posix-dependency-true-distribution-1110.md`。

前置依赖：`fix-legacy-test-failures`（SPEC-0）先清零存量失败（12 failed / 10181 passed 基线，用户定夺独立前置 SPEC），本 SPEC 验收口径维持「全量绿」。

**现场 grep 修正（2026-11-10，评审复核实测一致，权威于评估文档的侦察估计）**：core/ 含 `/proc/` 字面量文件 16 个（评估估 14；守卫 MUST 按裸字面量口径断言——`"/proc/` 双引号前缀口径实测仅命中 10 个，其余 6 文件为单引号/f-string 形态，双引号口径守卫会漏检回潮）；`import fcntl` 文件 19 个（= fs_utils 自身 + 5 个 NB 消费点 + 13 个其余，verify_contract.py 唯一位点即 NB）；`flock(` 调用 78 处（评估估 80；词面含极少量注释噪声，如 judge_gate.py:169，以真实调用位点为准）；`start_new_session=` 33 处词面 / 18 文件（评估估 ~38 含 bin/；= 31 处 `=True` 位点 + runner.py:7030 动态 passthrough（`spawn_spec.start_new_session` 可为 False，直杀直接子进程语义）+ :6793 注释词面——passthrough 位点 MUST 经带 `new_session` 参数的 pal 形态保语义迁移，MUST NOT 盲改无条件 detached）；`os.killpg(` 直调 3 处（proc_utils.py:390 内部 + serving_registry.py:482/502 探活）；另 core/ 平台判断分支现存命中：admin_stray_wip.py:1143/1149 `os.name == "nt"`（W4b 一并迁出，见任务 4.3）。bin/（fenixd_supervisor、run_full_suite、dsh_acceptance、test_for、fenix_verify_contract、migrate_to_systemd）含 POSIX 面，**属 SPEC-2 托管链范畴，本 SPEC 不动**（守卫范围 = core/）。

## Goals

- Linux 全部行为零变化；既有 438 个测试文件断言零修改（守卫测试除外）+ 全量绿（依赖 SPEC-0 基线）。
- 平台判断收敛至 `core/platform/__init__.py` 单点；业务代码只 `from core.platform import api as pal`。
- core/ POSIX syscall 零散落，静态守卫钉死防回潮（guard_killpg 同款手法，零豁免）。
- 零新增第三方依赖。

## 非目标

- win32.py 真实实现（SPEC-2，本 SPEC 仅占位）；bin/ 脚本迁移；pytest win32 `thread` 方法；psutil/portalocker/pywin32 引入；Linux 冒烟人工验证（reviewer/人工步骤，不进 tasks.md）。

## Decisions

1. **分层与分发**（评估 §5.1）：`core/platform/api.py` 类型化接口 + `linux.py` 平移 + `win32.py` 占位 + `__init__.py` 按 `sys.platform` 单点分发。
2. **向后兼容策略**：proc_utils / fs_utils / systemd_hosting 公开签名原样保留、内部转发 PAL——存量测试调用点零改动，这是 Linux 零回归的最小侵入保证。
3. **W1 前置锁参数扩展**（builder check 定夺）：`with_file_lock` 先加 `nonblocking` / `timeout_s` 可选参数（默认阻塞 LOCK_EX 不变），五个 NB fail-fast 消费点显式传参保语义，否则收敛即引入挂死回归。
4. **守卫零豁免**（builder check 定夺）：16 个 `/proc/` 文件 + serving_registry killpg 探活直调 + admin_stray_wip.py 平台判断分支全部迁 PAL（W4b），守卫测试启用排在 W4b/W5 之后（否则守卫出生即红）。守卫断言调用/导入语法与字符串字面量（POSIX 面九类，含 from-import 变体与 `/proc/` 裸字面量口径；平台判断面 `sys.platform` / `platform.system` / `os.name`，豁免整个 `core/platform/`），非注释词面。
5. **任务顺序**：W2 与 W1 参数扩展可先行（纯收敛独立可合）→ W3 骨架 → W4 转发化 → W4b 消费端迁移 → W5 spawn 收敛 → W6 守卫收尾。
6. **B 组三态语义**（评估 §8-R6 预埋）：探活接口返回 alive/dead/unknown，Linux 后端 unknown 不出现（/proc 恒可用），语义锚点为 SPEC-2 psutil 路径预埋；现行 fail-closed 行为不变。

## Risks

- **锁语义翻转挂死**：NB 消费点漏迁移 → 回归挂死。缓解：任务 1.2 显式枚举五个消费点，单测断言立即返回。
- **守卫出生即红**：迁移未完成先启用守卫。缓解：任务依赖顺序（§6 组排在 §4/§5 后）。
- **热路径原子写收敛引入回归**：runner/state_machine 是高频写路径。缓解：收敛 = 行为等价搬运（temp+replace 模式逐条对齐），既有测试全绿兜底。
- **/proc 读点语义细微差异**：16 文件读法各异（cmdline/stat/cwd/readlink/net tcp/environ）。缓解：linux.py 逐条平移原实现，diff 审查 + B 组单测逐接口对齐。

## 验收说明

- 机械验收（tasks.md 内）：全量 `python3 -m pytest tests/ -q` 零失败；守卫测试全绿；`linux.py` 与被平移源实现逐条对照自检表。
- 人工验收（不进 tasks.md，reviewer/人工执行）：Linux 冒烟（daemon 起停、一个 SPEC 全链、dashboard 正常）；`git diff` 审查确认平移等价。
