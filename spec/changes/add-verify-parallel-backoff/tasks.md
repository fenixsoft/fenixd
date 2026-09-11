# 任务：add-verify-parallel-backoff

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_verify_parallel_backoff.py
  kind: new
```

## 1. 降档标记写入（pm_engine 写端）

- [x] 1.1 `_handle_env_blocked_inconclusive`：attempts≥2 的重验分支（`attempts < max_attempts`）计算 `override = max(1, base >> (attempts - 1))`（base=配置 `verify_engine.max_parallel`，经 `_pm._get_config` 读取）并随既有 `update_spec` 写入 `_verify_parallel_override`；attempts==1 分支不写（TDD：先写「首次不降档」「连续递减」「低配置触底」三测）
- [x] 1.2 非 inconclusive 判定分支（`_handle_env_blocked_inconclusive` 返回 False 处）清除 `_verify_parallel_override`（存在才清，避免每轮无谓写盘）；升级/停验分支（attempts≥max）保持 override 原值不动——冻结待人工时保留现场证据（TDD：健康轮复位测）

## 2. 降档读取与可观测（verify_engine 读端）

- [x] 2.1 `verification.py` 构造 `VerifyEngine` 处读 spec attrs `_verify_parallel_override`，非空时 `engine.max_parallel = override`（构造签名不变，测试兼容）
- [x] 2.2 `engine.py` 启动日志：override 生效时并行度后附「（inconclusive 降档）」标记；`report.json` 顶层写 `effective_parallel`（所有轮都写，正常轮=配置值）（TDD：降档轮日志+report、正常轮无标记两测）

## 3. 复位点同步

- [x] 3.1 `state_machine.py` unfreeze 清零块（:580 附近）同步清 `_verify_parallel_override`（同一原子写）
- [x] 3.2 `dispatch.py` fast-track verified 清零块（:2566 附近）同步清 `_verify_parallel_override`；全链 verified（非 fast-track）落点若已清 `_inconclusive_attempts` 则同样同步（TDD：解冻/verified 复位两测）

## 4. 回归与收尾

- [x] 4.1 既有 inconclusive 门禁测试（`tests/` 下 verification 相关）全绿——确认降档标记不破坏 attempts 计数/停验/升级行为
- [x] 4.2 `tasks.md` 全勾后跑本 SPEC 全部测试确认；确认 `spec/changes/add-verify-parallel-backoff/` 提交干净
