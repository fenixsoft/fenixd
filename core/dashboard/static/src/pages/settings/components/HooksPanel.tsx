/**
 * HooksPanel — 设置页「Hook」面板（add-spec-hooks）。
 *
 * 管理全局 hooks（config.hooks.global 增删改/启停）+ 跨 spec 最近执行记录。
 * 结构复用共享组件 HookManager；保存经设置页 onSave 统一走 /api/config。
 *
 * 作用域说明：hook 配置仅项目级（.fenix/config.yaml），设置页菜单仅在
 * 项目级作用域下展示本页签（见 settings/index.tsx），故 project 必传。
 */

import { Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import HookManager from '@/components/HookManager';
import { getHookAudit } from '@/services/dashboard';
import type { ConfigData, HookAuditRecord, HookConfig } from '@/services/dashboard';

const { Text } = Typography;

interface HooksPanelProps {
  /** 设置页统一保存回调（写回 /api/config） */
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void> | void;
  /** 项目级作用域的项目名（本面板仅项目级可达） */
  project: string;
}

export default function HooksPanel({ config, onSave, project }: HooksPanelProps) {
  const [audit, setAudit] = useState<HookAuditRecord[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const hooksCfg = config.hooks ?? {};
  const globalHooks: HookConfig[] = Array.isArray(hooksCfg.global) ? hooksCfg.global : [];

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
    setSaving(true);
    try {
      await onSave({
        hooks: {
          ...(config.hooks || {}),
          global: nextGlobal,
        },
      });
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <Typography.Title level={5} style={{ marginTop: 0 }}>全局 Hook 订阅</Typography.Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        全局 hooks 对所有 SPEC 生效（SPEC 详情页 Hook 页签可配置 SPEC 级 hook，两者取并集）。
        动作失败会写审计日志并产生站内告警，不会自动重试。
      </Text>
      <HookManager
        hooks={globalHooks}
        onSave={handleSave}
        saving={saving}
        audit={audit}
        auditLoading={auditLoading}
        hideEffective
      />
    </div>
  );
}
