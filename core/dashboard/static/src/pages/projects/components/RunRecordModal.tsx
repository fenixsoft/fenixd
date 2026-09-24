// 运行记录最大化弹窗：时间轴「查看运行记录」旁的全屏入口，打开即占满视口。
// ClaudeOutputPane 依赖父容器高度约束，body 用 flex column + minHeight:0 提供全高滚动区。
import { Modal } from 'antd';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { MAXIMIZED_MODAL_STYLE, MAXIMIZED_WIDTH, maximizedBodyHeight } from '@/components/useMaximizeModal';

interface RunRecordModalProps {
  runId: string | null;
  project: string;
  onClose: () => void;
}

export default function RunRecordModal({ runId, project, onClose }: RunRecordModalProps) {
  return (
    <Modal
      title={`运行记录 · ${runId ?? ''}`}
      open={!!runId}
      onCancel={onClose}
      footer={null}
      width={MAXIMIZED_WIDTH}
      style={MAXIMIZED_MODAL_STYLE}
      styles={{ body: { height: maximizedBodyHeight(), display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
    >
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, background: '#fafafa' }}>
        {runId && <ClaudeOutputPane key={runId} runId={runId} project={project} />}
      </div>
    </Modal>
  );
}
