import { Modal } from 'antd';
import { useEffect, useState } from 'react';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

interface AdminRunModalProps {
  project: string;
  spec?: string;
  adminRunId: string;
  open: boolean;
  onClose: () => void;
}

export default function AdminRunModal({ project, spec, adminRunId, open, onClose }: AdminRunModalProps) {
  const [eventCount, setEventCount] = useState(0);
  // 关闭时 destroyOnHidden 会卸载 ClaudeOutputPane，重开瞬间标题残留上一次 run 的计数，打开即清零待重新上报。
  useEffect(() => {
    if (open) {
      setEventCount(0);
    }
  }, [open]);
  const { modalProps, maximizeButton } = useMaximizeModal({
    defaultWidth: '80vw',
    defaultBodyHeight: '72vh',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', paddingTop: 12 },
  });

  return (
    <Modal
      title={
        <MaximizeTitle
          text={spec ? `${spec} · Admin 处置过程` : 'Admin 处置过程'}
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
                共 {eventCount} 条事件
              </span>
            )
          }
          button={maximizeButton}
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
          // [fenix-ignore:4dcf5fe936bb] 应用固定浅色主题，无暗色切换能力，硬编码浅色值不影响主题适配
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          padding: 12,
          background: '#fafafa',
        }}
      >
        <ClaudeOutputPane runId={adminRunId} project={project} onEventsCount={setEventCount} />
      </div>
    </Modal>
  );
}
