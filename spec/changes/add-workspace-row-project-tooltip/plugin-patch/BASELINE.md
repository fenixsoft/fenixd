# 宿主基线快照（add-workspace-row-project-tooltip）

> 快照时刻：2026-11-10（实现 run 起始）。宿主仓 `/root/dsh-plugins` 的 dsh-plugins
> 主树不做任何 git 操作（ADR-339 先例纪律）；本文件与 `baseline/` 快照、
> `fenix-dsh-dashboard-bridge.patch` 构成补丁镜像三件套，供评审与恢复对账。

## 宿主 HEAD

```
5ae9e41bd5213b3faf0bcef4d9e2465bbcd8f8d5
```

## 快照文件清单（拟触达 4 文件，`baseline/fenix-dsh-dashboard-bridge/` 相对路径）

- `src/client/projectSync.ts`
- `src/client/panels.tsx`
- `tests/projectSync.test.ts`
- `tests/srcContract.test.ts`

快照内容 = 快照时刻宿主工作树当前内容（只读复制，未做任何改写）。

## 宿主未提交态（`git -C /root/dsh-plugins status --porcelain` 原样）

```
 M fenix-dsh-brand-fenix/client.js
 M fenix-dsh-chat-polish/client.js
 M fenix-dsh-dashboard-bridge/src/client/index.ts
 M fenix-dsh-dashboard-bridge/src/client/panels.tsx
 M fenix-dsh-dashboard-bridge/src/client/projectSync.ts
 M fenix-dsh-dashboard-bridge/tests/projectSync.test.ts
 M fenix-dsh-dashboard-bridge/tests/srcContract.test.ts
?? .claude/
?? fenix-dsh-auth/
```

拟触达 4 文件在快照时刻**均处于未提交修改态**（另有 index.ts 及两个无关插件
文件同态）。按先例纪律：宿主既有未提交改动**不回退、不混入补丁**——本 SPEC
改动直接叠加在工作树现状之上，补丁 diff 以 `baseline/` 快照（含既有未提交态）
为基准生成，因此本补丁只含本 SPEC 引入的增量（diff 上下文中可能带出既有未
提交改动已固化的行，属预期）。

## 恢复备忘

- 本 SPEC 改动回退：`patch -p1 -R < fenix-dsh-dashboard-bridge.patch`（在
  `/root/dsh-plugins/fenix-dsh-dashboard-bridge/` 下执行）即可恢复到快照态；
  或从 `baseline/fenix-dsh-dashboard-bridge/` 逐文件复制覆盖宿主同名文件。
- 宿主仓无远程推送、无 git 操作授权：任何恢复动作只动工作树文件，不动
  git 历史。
- `pnpm build` 后 `lib/` 产物经 symlink 即时映射（既有部署链）；回退补丁后
  须重跑 `pnpm build && systemctl restart dsh-web` 才回到快照运行态。

## 追加修复（fix-workspace-tip-overlap，2026-11-10）

交付后用户报告缺陷：fenix 行 hover 时原生 tooltip 未被屏蔽，两卡重叠。
根因：落地版 `createNativeTipSuppressor` 为「富提示 show 时才 start 的观察
器」，与原生 tooltip 同为 500ms 延迟，竞速失败错过 portal 节点的 add 事件。
修复（用户裁决绕过立项直接修改宿主仓，未走 SPEC 流程）：

- `wsTooltip.ts`：消解器改常驻型 `createNativeTipSuppressor(getNames)` →
  `{start, refresh, stop}`——安装期 start（存量 body.children 兜底扫描 +
  body childList/subtree 常驻观察），命中=body 直子文本含任一已装层项目名
  且无 `WORKSPACE_TIP_ATTR`；refresh 供项目移除后解Hide；stop 全解。
- `panels.tsx`：新增 `installedNames` 集合与消解器生命周期接线（换层/新挂
  写名、removeOverlaysOfName 删名+refresh、store 订阅 refresh、teardown stop）。

上 diff 已重生成，含本次修复增量。活站复验（playwright，token 会话）：
fenix 行 hover 原生 display:none + 富卡独显；非 fenix 行（nongit）原生照常
display:contents + 富卡 0；换行无残卡。vitest 89 过、pnpm build 过、
systemctl restart dsh-web 后生效。
