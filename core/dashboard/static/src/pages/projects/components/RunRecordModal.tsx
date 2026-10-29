// 运行记录最大化弹窗：时间轴「查看运行记录」旁的全屏入口，打开即占满视口。
// ClaudeOutputPane 依赖父容器高度约束，body 用 flex column + minHeight:0 提供全高滚动区。
// 品牌投影（add-harness-brand-projection 3.1）：harness 取自时间轴 run 节点
// meta（run_metrics 旁路行透出），经 HarnessBrandProvider 注入对话 pane——
// 缺失/未知值走回退链（2026-10-29 用户定稿：缺失 → 中性「AI Assistant」/
// 首字母徽标；未注册值 → 首字母徽标）。
// 暗色宿主防御（2026-10-29）：内容树为亮色设计（#fafafa 硬编码底），但弹窗
// body 是 portal——指挥中心等暗色 antd 宿主下 Button/Switch/Typography 吃
// 外层 dark token 白字亮底不可读；内层亮色 Provider 隔离（亮色宿主下幂等）。
// tailwind shadcn 语义变量（hsl(var(--*))）在 portal 挂载点无法继承
// .claude-msg-pane——内容根挂 .claude-msg-portal 显式注入（global.less）。
import { ConfigProvider, Modal, theme } from 'antd';
import { ClaudeOutputPane, HarnessBrandProvider } from '@/components/claude-msg';
import { MAXIMIZED_MODAL_STYLE, MAXIMIZED_WIDTH, maximizedBodyHeight } from '@/components/useMaximizeModal';

interface RunRecordModalProps {
  runId: string | null;
  project: string;
  // run meta 的 harness 字段（存量 run 无该字段 → undefined → 中性品牌）
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
      <ConfigProvider
        // token 继承外层 Provider：colorBgBase 显式覆盖回白（暗色宿主注入的
        // #000000 不重置会把暗底漏进弹窗）；colorPrimary 等其余继承无妨
        theme={{ algorithm: theme.defaultAlgorithm, token: { colorBgBase: '#ffffff' } }}
      >
        <div className="claude-msg-portal" style={{ flex: 1, minHeight: 0, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, background: '#fafafa' }}>
          {runId && (
            <HarnessBrandProvider harness={harness}>
              <ClaudeOutputPane key={runId} runId={runId} project={project} />
            </HarnessBrandProvider>
          )}
        </div>
      </ConfigProvider>
    </Modal>
  );
}
