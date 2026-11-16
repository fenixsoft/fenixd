# Windows 服务化后 Path.home() 漂移导致「用户级配置文件不存在」误报

- 日期：2026-11-16
- 来源：用户真机（Windows 11 Pro，fenixd v0.1.5）部署诊断；服务器 win-vm 现象同构（差异正常）
- 状态：待蒸馏 → 建议并入 daemon-runtime/windows-native-support.md「服务环境注入与自检」条与 provider-models 分级配置页

## 现象

install.md 全新部署后，演示项目 Dashboard 设置页仍显示「用户级配置文件不存在，表单为默认值」；
`/api/config` 返回 `raw_exists=False, scope=user`，但 `%USERPROFILE%\.fenix\config.yaml` 实际存在。

## 根因链

1. dashboard/supervisor 以 NSSM 服务（ObjectName=LocalSystem）运行，服务注册时
   `AppEnvironmentExtra` 未注入 `USERPROFILE`。
2. SCM 为 LocalSystem 进程提供的环境块里 `USERPROFILE=C:\WINDOWS\system32\config\systemprofile`。
3. `core/config.py:20` `USER_CONFIG_DIR = Path.home() / ".fenix"` 在 import 期按该错误
   home 一次性绑定 → 读不到真实用户级配置 → `raw_exists=False` → 前端按 scope=user
   渲染「用户级配置文件不存在」（core/dashboard/static/src/pages/settings/index.tsx L613-617）。

## 修复（真机已验证有效）

管理员 PowerShell：对 dashboard 与 supervisor 两服务的
`HKLM:\SYSTEM\CurrentControlSet\Services\<svc>\Parameters` 写
`AppEnvironmentExtra`（MultiString，supervisor 侧先读后追加）注入
`USERPROFILE=C:\Users\<user>`，`nssm restart` 两服务后
`(Invoke-RestMethod http://127.0.0.1:8787/api/config).raw_exists` 转 True。

## 框架级修法候选（立项 fix-windows-service-userprofile）

1. `install_unit`（core/platform/win32.py:1706）默认注入 USERPROFILE（LocalSystem
   服务取调用者 profile；合并语义已有，read-modify-write 不清既有条目）。
2. `USER_CONFIG_DIR` 支持 `FENIX_HOME` 环境变量覆盖（防御性逃生口）。
3. 设置页提示文案携带实际解析路径（`str(USER_CONFIG_PATH)`），漂移一眼可见。
4. install.md §8 服务注册步骤把 USERPROFILE 注入升为必做；G1-01b 复验回填。

## 溯源

- 诊断报告：用户真机会话产出（fenixd-dashboard-config-diagnosis.md，2026-11-16 16:35）
- 关联既有知识：provider-models/hierarchical-config.md、_inbox/done/user-config-fresh-install-bootstrap.md、
  daemon-runtime/windows-native-support.md（服务环境注入与自检、env_defect）
