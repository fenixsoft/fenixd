# Dashboard 上游曾随 dsh-web 重启被杀 → wsnav 拦截层静默不装层（2026-11-27）

## 现象

dsh web 侧栏点击 fenix 工作区名称无法进入 spec 列表页。两类症状并存：

1. 用户旧标签页：`[fenix-dsh-dashboard-bridge] 切换项目面板失败：cannot get required service "layout" in inactive context`。
2. 全新会话：点击零响应、无任何报错，`[data-fenix-wsnav]` 拦截层 0 个。

## 根因（两层，均非插件导航代码回归）

**主因（fresh 会话零响应）**：`fenix_dashboard.py --serve` 此前作为 **dsh-web cgroup 子进程**存活，`systemctl restart dsh-web` 会把它一起杀掉（11-26 dsh 0.2.2-rc.5 升级重启、本次排查中的重启均复杀）。上游 127.0.0.1:8787 死 → bridge 项目同步 `/fenix-dashboard/api/projects` **502** → `projectGroupStore.projects=[]` → panels.tsx rescan 走「projects 空分支」（`removeAllOverlays`+return，**设计上零日志零 warn**）→ 拦截层永不安装。插件侧 list 捕获、rescan 三通道、map 匹配链全部健康（插桩实测 sig `6:7:7:6:6`，6/6 层正常安装）。

**次因（旧标签页报错）**：陈旧会话。用户页面持有 dsh-web 重启前下发的旧 bundle（console 栈行号 6719 ≠ 现行 bundle 6836；URL 参数风格 `v=` ≠ 现行 `rev=`）。dsh-web 重启后其页面经 websocket 重连存活，但插件 fiber 已 inactive（服务 re-provide 未重放），残存拦截层点击即抛 inactive context。**刷新页面即解**。

## 修复

```bash
python3 - "$FENIX_DIR" <<'PYEOF'   # FENIX_DIR=.fenix 解析出的框架根
from core.systemd_hosting import install_dashboard_unit
install_dashboard_unit(framework)  # 生成 fenix-dashboard.service 并 enable --now
PYEOF
```

unit 承载（父进程 PID 1）后 dashboard 不再随 dsh-web 重启死亡；回归验证：restart dsh-web 后 fenix-dashboard 仍 active、刷新后 6/6 工作区拦截层安装、点击 fenixd 正常进入项目详情 spec 列表 iframe。

## 排查教训

- **网络证据要核对会话代际**：playwright console log 跨页面加载累积，boot 期 `api/projects 200×2` 属重启前旧会话；重启后新会话实为 502。判定「数据面正常」前先确认 fetch 与插件 apply 在同一页面生命周期。
- rescan 的「projects 空」分支零日志是刻意静默设计（boot 早期正常态），排查时与故障态不可区分——对静默分支做临时插桩（TEMP-DEBUG + pnpm build + restart + token 重登）是定位此类问题的最短路径。
- dashboard 502 的真因在**进程托管方式**，不在插件代码；bridge 对上游死掉的降级（warn「拉取项目列表失败」+ 层不装）行为符合设计。
