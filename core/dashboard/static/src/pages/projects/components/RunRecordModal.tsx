// 运行记录最大化弹窗：时间轴「查看运行记录」旁的全屏入口，打开即占满视口。
// ClaudeOutputPane 依赖父容器高度约束，body 用 flex column + minHeight:0 提供全高滚动区。
// 品牌投影（add-harness-brand-projection 3.1）：harness 取自时间轴 run 节点
// meta（run_metrics 旁路行透出），经 HarnessBrandProvider 注入对话 pane——
// 缺失/未知值走回退链（缺省 claude / 首字母徽标）。
import { Modal } from 'antd';
import { ClaudeOutputPane, HarnessBrandProvider } from '@/components/claude-msg';
import { MAXIMIZED_MODAL_STYLE, MAXIMIZED_WIDTH, maximizedBodyHeight } from '@/components/useMaximizeModal';

interface RunRecordModalProps {
  runId: string | null;
  project: string;
  // run meta 的 harness 字段（存量 run 无该字段 → undefined → 缺省 claude 品牌）
  harness?: string;
  onClose: () => void;
}

export default function RunRecordModal({ runId, project, harness, onClose }: RunRecordModalProps) {
  return (
    <Modal
      title={`运行记录 · ${runId ?? ''}`}
      open={!!runId}
      onCancel={onClose}
      destroyOnHidden
      footer={null}
      width={MAXIMIZED_WIDTH}
      style={MAXIMIZED_MODAL_STYLE}
      styles={{ body: { height: maximizedBodyHeight(), display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
    >
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, background: '#fafafa' }}>
        {runId && (
          <HarnessBrandProvider harness={harness}>
            <ClaudeOutputPane key={runId} runId={runId} project={project} />
          </HarnessBrandProvider>
        )}
      </div>
    </Modal>
  );
}
