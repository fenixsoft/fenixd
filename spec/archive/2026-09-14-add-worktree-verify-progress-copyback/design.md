# Design: add-worktree-verify-progress-copyback

## Context

2026-09-09 双事故根因（详见 proposal）：fast-track agent 在 worktree 内用 Bash 相对路径写
per-spec 验证产物（planner-scenario-batching hook deny 后的绕道行为），产物落 worktree
真实 `.fenix/` 目录。runner 成功路径（`core/agent_runner/runner.py:2114-2125`）只拷
worktree **根部** `.fenix-run-result.json` → 主树共享文件 `.fenix/.fenix-run-result.json`；
per-spec 目录无拷回机制，worktree 清理即销毁。共享文件随后被下一 spec 成功覆盖
（spec 印章不符 → 读侧忽略），Dashboard「场景结果」页签数据蒸发。

事故数据靠 run 转录（`.fenix/runs/impl-*.jsonl` 内 agent 的 heredoc/构造脚本）手工恢复。
本 spec 在框架层收口，使任何 agent 写入路径形态下产物都不再丢失。

## Goals / Non-Goals

- **Goals**: 成功收尾时 worktree per-spec 验证产物目录 → 主树的确定性拷回；防陈旧覆盖；
  fail-open。
- **Non-Goals**:
  - 不改 planner-scenario-batching hook 的拦截规则与处方文案（分批机械化是独立目标，
    Bash 绕行治理不在本 spec 范围）；
  - 不做失败路径（worktree_kept 保留给重派继承）的拷回——重派继承语义依赖 worktree
    内现场原样保留；
  - 不改共享文件 `.fenix/.fenix-run-result.json` 的既有拷贝契约与读侧印章校验。

## Decisions

### D1 拷贝点：runner 成功路径既有拷贝点旁（唯一收口点）

放在 `runner.py:2114` 既有「根 result → 共享文件」拷贝的同级 `if success:` 块内、
worktree 清理之前。该块是 implementer / fast-track / repair / verifier 全部 worktree
run 的成功必经点，一处收口覆盖全部 agent 类型；fast-track 的延迟清理（dispatch 层
`_release_fast_track_worktree`）发生在 runner 返回之后，时序天然满足「拷回先于清理」。

### D2 拷贝语义：逐文件 copy2 + mtime 守卫（非整目录 replace）

`shutil.copytree(..., dirs_exist_ok=True)` 会把主树目录整体置于拷贝语义下，存在两类
污染风险。改为遍历 worktree 目录逐文件 `shutil.copy2`：

- 主树同路径**缺失** → 拷入（事故主场景）；
- worktree 版本 mtime **较新** → 覆盖（agent 在 worktree 内更新了已存在文件的场景）；
- 主树版本**较新** → 跳过（worktree 复用继承陈旧产物时，保护主树较新的冻结场景集、
  `impl-result.json` 等不被回灌）。

copy2 保留源 mtime，使跨轮次比较稳定。子目录（若 agent 创建了嵌套结构）递归同样处理。

### D3 fail-open 与日志

拷贝循环包 try/except OSError，单文件失败记 WARNING（logger 名 `agent_runner`，含
spec 名与源/目标路径）后继续其余文件；整体失败不抛出。与既有根 result 拷贝的
「except OSError: pass」风格一致但日志更可诊断（事故复盘需要知道拷回是否发生过）。

### D4 无产物目录零动作

`wt_path/.fenix/verify-progress/<spec>/` 不存在时直接返回——不创建主树目录、不打日志
（正常形态 agent 全走主树绝对路径写入，此为多数 run，避免日志噪音）。

## Risks / Trade-offs

- **mtime 不可靠文件系统** → 极端情况下守卫可能误判新旧；影响面仅为「少拷一个文件」，
  与修复前行为一致（fail-open），无恶化。
- **拷回覆盖正在被读侧读取的文件** → 逐文件 copy2 原子性弱于 os.replace；但读侧
  （parse_run_result_scenarios 等）均有 JSONDecodeError 兜底，且写入发生在 run 收尾
  低频点，风险可忽略。
- **verifier run 的 worktree 也触发拷回** → mtime 守卫使陈旧继承产物不会覆盖主树；
  agent 新写的文件被拷回恰是期望行为（full 模式 verifier 偶发相对路径写入同样受益）。

## Migration Plan

无迁移——纯增量代码路径，存量 spec 的产物已恢复或不可恢复，不影响。

## Open Questions

（无）
