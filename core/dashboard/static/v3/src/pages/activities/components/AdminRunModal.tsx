import { Modal } from 'antd';
import { useState } from 'react';
import { ClaudeOutputPane } from '@/components/claude-msg';

interface AdminRunModalProps {
  project: string;
  spec?: string;
  adminRunId: string;
  open: boolean;
  onClose: () => void;
}

export default function AdminRunModal({ project, spec, adminRunId, open, onClose }: AdminRunModalProps) {
  const [eventCount, setEventCount] = useState(0);

  return (
    <Modal
      title={
        <span>
          {spec ? `${spec} · ` : ''}Admin 处置过程
          {eventCount > 0 && (
            <span style={{ fontSize: 12, color: '#8c8c8c', fontWeight: 400, marginLeft: 8 }}>
              共 {eventCount} 条事件
            </span>
          )}
        </span>
      }
      open={open}
      onCancel={onClose}
      width="80vw"
      footer={null}
      destroyOnHidden
      styles={{ body: { height: '72vh', display: 'flex', flexDirection: 'column', paddingTop: 12 } }}
    >
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
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
