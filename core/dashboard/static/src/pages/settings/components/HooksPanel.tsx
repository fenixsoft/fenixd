/**
 * HooksPanel — 设置页「Hook」面板（add-spec-hooks）。
 *
 * 管理全局 hooks（config.hooks.global 增删改/启停）+ 跨 spec 最近执行记录。
 * 结构复用共享组件 HookManager；保存经设置页 onSave 统一走 /api/config。
 *
 * dashboard-push-restart 2.1：逃生键 hooks.push_restart_dashboard 开关
 * （SPEC pushed 终态自动重启 dashboard 的总开关，缺省 true）。
 *
 * 作用域说明：hook 配置仅项目级（.fenix/config.yaml），设置页菜单仅在
 * 项目级作用域下展示本页签（见 settings/index.tsx），故 project 必传。
 */

import { App, Card, Checkbox, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import HookManager from '@/components/HookManager';
import { getHookAudit } from '@/services/dashboard';
import type { ConfigData, HookAuditRecord, HookConfig, HooksConfig } from '@/services/dashboard';
// 「重拉基底 + hooks 段整体替换」与 SPEC 详情 SpecHooksSection 共用单源
// （code-review item 7add07b1e0e8）
import { saveHooksSection } from '@/services/hooksSection';

const { Text } = Typography;

interface HooksPanelProps {
  /** 设置页统一保存回调（写回 /api/config） */
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void> | void;
  /** 项目级作用域的项目名（本面板仅项目级可达） */
  project: string;
}

/** 逃生键读取：hooks.push_restart_dashboard 缺省 true，仅显式 false 关闭
 * （与后端 hook_config 注入门同口径：非法值按缺省开启）。 */
export function pushRestartEnabledFromConfig(hooksCfg: unknown): boolean {
  if (hooksCfg && typeof hooksCfg === 'object' && !Array.isArray(hooksCfg)) {
    return (hooksCfg as Record<string, unknown>).push_restart_dashboard !== false;
  }
  return true;
}

/** 逃生键写回参数：保留 hooks 段其余键（global/specs 等）整体替换落盘。 */
export function pushRestartSavePayload(
  hooksCfg: unknown,
  on: boolean,
): { hooks: Record<string, unknown> } {
  const base =
    hooksCfg && typeof hooksCfg === 'object' && !Array.isArray(hooksCfg)
      ? (hooksCfg as Record<string, unknown>)
      : {};
  return { hooks: { ...base, push_restart_dashboard: on } };
}

export default function HooksPanel({ config, onSave, project }: HooksPanelProps) {
  const { message } = App.useApp();
  const [audit, setAudit] = useState<HookAuditRecord[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // 保存重入守卫（比照 useGatedFormPanel 的 savingRef 口径）：本面板两个写盘
  // 入口（handleSave / handleTogglePushRestart）都是「getConfig 重拉基底 +
  // onSave 整体替换 hooks 段」的异步链，setSaving 渲染生效存在 React 调度
  // 间隙，重入防护若只有 Checkbox 的 disabled={saving} 视觉禁用，间隙内连点
  // 会并发两组写盘请求（后到者以自己重拉的基底覆盖先到者）；经 savingRef
  // 写读同帧原子短路，state 只负责按钮视觉反馈。两个入口共用一把锁
  // （写的是同一段 hooks 配置，交叉并发同样冲突）。
  const savingRef = useRef(false);

  const hooksCfg = config.hooks ?? {};
  const globalHooks: HookConfig[] = Array.isArray(hooksCfg.global) ? hooksCfg.global : [];
  const pushRestartOn = pushRestartEnabledFromConfig(config.hooks);

  // 加载跨 spec 最近执行记录
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!project) {
        setAudit([]);
        return;
      }
      setAuditLoading(true);
      try {
        const d = await getHookAudit(project, undefined, 20);
        if (!cancelled) setAudit(d.audit ?? []);
      } catch (e) {
        console.error('Failed to load hook audit:', e);
        if (!cancelled) message.error(`加载 hook 执行记录失败：${e instanceof Error ? e.message : e}`);
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [project]);

  const handleSave = async (nextGlobal: HookConfig[]) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      // 基底用保存前重拉的最新配置 + hooks 段整体替换抽为 saveHooksSection
      // 单源（「patch 存在即整体替换」语义见该模块头注释，
      // code-review item 26586e4395cd 原始修复点）
      await saveHooksSection(
        project,
        (latestHooks) => ({ ...latestHooks, global: nextGlobal }),
        onSave,
      );
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : e}`);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  // dashboard-push-restart 2.1：逃生键切换即写回（checkbox 切换触发配置写回
  // 调用，经设置页 onSave 统一走 /api/config）
  const handleTogglePushRestart = async (on: boolean) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      // 基底用保存前重拉的最新配置（同 handleSave 走 saveHooksSection 单源：
      // patch 存在即整体替换，快照合并会静默回退他处的修改）
      // （code-review item 26586e4395cd；单源收敛 f37b4973a131）
      await saveHooksSection(
        project,
        // payload 仍复用 pushRestartSavePayload（含 hooks 段非对象兜底 {} 口径）；
        // saveHooksSection 以 { hooks: <段> } 收口，故取 .hooks 段
        (latestHooks) => pushRestartSavePayload(latestHooks, on).hooks as HooksConfig,
        onSave,
      );
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : e}`);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <div>
      {/* 与其他设置页签统一的家规标题模式（h3 默认顶距），勿改 Typography.Title+marginTop:0 */}
      <h3>全局 Hook 订阅</h3>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        全局 hooks 对所有 SPEC 生效（SPEC 详情页 Hook 页签可配置 SPEC 级 hook，两者取并集）。
        订阅「全部SPEC完成（all-done）」可在所有 SPEC 均处于完成/已推送终态时触发动作
        （如重启 daemon，作为全部任务自然收口后的安全重启点）。
        动作失败会写审计日志并产生站内告警，不会自动重试。
      </Text>
      <HookManager
        hooks={globalHooks}
        onSave={handleSave}
        saving={saving}
        audit={audit}
        auditLoading={auditLoading}
        hideEffective
        allowProjectEvent
      />
      {/* dashboard-push-restart 2.1：推送自动重启逃生键 */}
      <h3 style={{ marginTop: 24 }}>推送自动重启</h3>
      <Card style={{ marginTop: 12 }} data-testid="push-restart-dashboard-card">
        <Checkbox
          data-testid="push-restart-dashboard-switch"
          checked={pushRestartOn}
          disabled={saving}
          onChange={(e) => handleTogglePushRestart(e.target.checked)}
        >
          <span className="switch-inline-label">
            SPEC push 后自动重启 dashboard
            <span className="label-note">（hooks.push_restart_dashboard）</span>
          </span>
        </Checkbox>
        <div>
          <Text type="secondary" data-testid="push-restart-dashboard-desc">
            SPEC push 后自动重启 dashboard 以加载最新代码；重启走 tmux 会话原窗格，
            60s 内重复 push 自动去抖，未运行 dashboard 的环境静默跳过。
            关闭后 pushed 不再触发重启，既有 hook 配置不受影响。约 30s 配置热更新生效。
          </Text>
        </div>
      </Card>
    </div>
  );
}
