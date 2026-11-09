# BASELINE — fenix-dsh-dashboard-bridge 基线快照

> 快照时刻：2026-11-09（SPEC move-project-nav-to-workspace-rows 实施前）
> 快照对象：`/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 拟触达 5 文件
> 用途：`plugin-patch/fenix-dsh-dashboard-bridge.patch` 的 diff 左侧基准（baseline → 改后状态）

## 宿主仓 HEAD

```
5ae9e41bd5213b3faf0bcef4d9e2465bbcd8f8d5
```

## 宿主仓 status --porcelain（快照时刻原样）

```
 M fenix-dsh-brand-fenix/client.js
 M fenix-dsh-chat-polish/client.js
 M fenix-dsh-dashboard-bridge/src/client/panels.tsx
 M fenix-dsh-dashboard-bridge/tests/srcContract.test.ts
?? .claude/
```

## 快照文件清单（baseline/ 镜像路径 ↔ 宿主路径）

| baseline/ 镜像 | 宿主路径（相对 fenix-dsh-dashboard-bridge/） |
| --- | --- |
| `baseline/fenix-dsh-dashboard-bridge/src/client/panels.tsx` | `src/client/panels.tsx` |
| `baseline/fenix-dsh-dashboard-bridge/src/client/index.ts` | `src/client/index.ts` |
| `baseline/fenix-dsh-dashboard-bridge/src/client/projectSync.ts` | `src/client/projectSync.ts` |
| `baseline/fenix-dsh-dashboard-bridge/tests/srcContract.test.ts` | `tests/srcContract.test.ts` |
| `baseline/fenix-dsh-dashboard-bridge/tests/projectSync.test.ts` | `tests/projectSync.test.ts` |

快照为**只读复制**（含宿主未提交改动的工作区现状），复制后经 `diff -r` 校验与宿主逐字节一致。

## 宿主未提交态备忘（重要）

宿主主树快照时刻含**未提交**改动（2026-11-03 徽标改造已部署未提交）：`fenix-dsh-brand-fenix/client.js`、`fenix-dsh-chat-polish/client.js`、`fenix-dsh-dashboard-bridge/src/client/panels.tsx`、`fenix-dsh-dashboard-bridge/tests/srcContract.test.ts`（另 `.claude/` 未跟踪目录与本项目无关）。

- 本 SPEC 基线快照**包含**该未提交态（即 `baseline/` 反映的是已部署工作区现状，非 HEAD 提交版）。
- 本 SPEC 补丁以「基线快照 → 改后状态」生成，**不得回退、不得混入**徽标改造本身的 diff——`panels.tsx`/`srcContract.test.ts` 中徽标改造内容在补丁两侧同现、互相抵消，补丁只呈现本 SPEC 的改动。
- 本 SPEC 不在 dsh-plugins 仓做任何 git 提交/回退操作（design.md D5）。

## 改后状态补记（2026-11-09 实施完成后）

- 宿主仓 HEAD 快照前后**无漂移**（`5ae9e41b`，未做任何 git 操作，符合 D5）。
- 改后 status：5 个拟触达文件全部 `M`（其中 `panels.tsx`/`srcContract.test.ts` 同时含徽标改造与本 SPEC 改动；`index.ts`/`projectSync.ts`/`projectSync.test.ts` 为本 SPEC 新增改动）。
- 补丁已生成：`fenix-dsh-dashboard-bridge.patch`（3582 行；`diff -ruN` 基线 → 宿主现状，pa/fenix-dsh-dashboard-bridge ↔ pb/fenix-dsh-dashboard-bridge 同布局）。
- 回放校验：干净目录 `patch -p1 --dry-run` 全过 → 真打 → 回放产物与宿主现状 5 文件逐字节 `cmp` 一致。
- 各文件改动规模（`diff | grep -c '^[<>]'`）：index.ts 156 行、panels.tsx 1565 行、projectSync.ts 149 行、srcContract.test.ts 858 行、projectSync.test.ts 286 行。
- 端到端验证证据：主树 `/root/fenixd/.fenix/verify-evidence/move-project-nav-to-workspace-rows/e2e-playwright-report.md`（11 Scenario 实拍断言 + console 零未处理异常核查）。

## 恢复路径

- 宿主改动后状态仅存在于宿主工作区 + 本仓 `plugin-patch/` 补丁镜像；dsh-plugins 仓无本 SPEC 提交。
- 回滚 = 对宿主 5 文件以 `baseline/` 镜像内容覆盖（或逆向应用 patch），再 `pnpm -C /root/dsh-plugins/fenix-dsh-dashboard-bridge build` + `systemctl restart dsh-web`。
- 风险备忘：用户日后在 dsh-plugins `git checkout/restore` 会同时丢弃徽标改造与本 SPEC 改动（两者均未提交）——徽标改造可另从其部署产物或历史备份找回，本 SPEC 改动可从本仓 `plugin-patch/` 补丁恢复。
