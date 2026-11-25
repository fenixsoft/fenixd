import { Modal } from 'antd';
import { useIntl } from '@umijs/max';
import { useDshPalette, useThemeScheme } from '@/utils/themeHooks';
import { useEffect, useState } from 'react';
import { ClaudeOutputPane, HarnessBrandProvider } from '@/components/claude-msg';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）

interface AdminRunModalProps {
  project: string;
  spec?: string;
  adminRunId: string;
  // add-harness-brand-projection 3.2：admin 车道 run meta 的 harness（经
  // run_activity 同口径的 run_metrics 旁路行透出）；缺失/未知值走回退链
  //（缺失 → 中性 AI Assistant / 未注册值 → 首字母徽标）
  harness?: string;
  open: boolean;
  onClose: () => void;
}

export default function AdminRunModal({ project, spec, adminRunId, harness, open, onClose }: AdminRunModalProps) {
  const pal = useDshPalette();
  const scheme = useThemeScheme();
  const intl = useIntl();
  const [eventCount, setEventCount] = useState(0);
  // 关闭时 destroyOnHidden 会卸载 ClaudeOutputPane，重开瞬间标题残留上一次 run 的计数，打开即清零待重新上报。
  useEffect(() => {
    if (open) {
      setEventCount(0);
    }
  }, [open]);
  const { modalProps, maximizeButton, isFullscreen } = useMaximizeModal({
    defaultWidth: '80vw',
    defaultBodyHeight: '72vh',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', paddingTop: 12 },
  });

  return (
    <Modal
      title={
        <MaximizeTitle
          text={spec
            ? intl.formatMessage({ id: 'ops.adminRun.titleWithSpec' }, { spec })
            : intl.formatMessage({ id: 'ops.adminRun.title' })}
          extra={
            eventCount > 0 && (
              <span
                style={{
                  fontSize: 12,
                  // [fenix-ignore:4dcf5fe936bb] 应用固定浅色主题，无暗色切换能力，硬编码浅色值不影响主题适配
                  color: '#8c8c8c',
                  fontWeight: 400,
                  marginLeft: 8,
                }}
              >
                {intl.formatMessage({ id: 'ops.adminRun.eventCount' }, { count: eventCount })}
              </span>
            )
          }
          button={maximizeButton}
          isFullscreen={isFullscreen}
        />
      }
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      {...modalProps}
    >
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          // 二轮验收（2026-11-25 用户指令「运行记录跟随主题」）：撤固定浅底，
          // 边/底走 pal 双档，深档透明落弹窗深壳；浅档字节不变
          border: `1px solid ${pal.border}`,
          borderRadius: 8,
          padding: 12,
          background: scheme === 'dark' ? 'transparent' : '#fafafa',
        }}
        className="claude-msg-portal"
      >
        <HarnessBrandProvider harness={harness}>
          <ClaudeOutputPane
            runId={adminRunId}
            project={project}
            onEventsCount={setEventCount}
            waitingText={intl.formatMessage({ id: 'ops.adminRun.waiting' })}
          />
        </HarnessBrandProvider>
      </div>
    </Modal>
  );
}
