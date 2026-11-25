// 运行记录最大化弹窗：时间轴「查看运行记录」旁的全屏入口，打开即占满视口。
// ClaudeOutputPane 依赖父容器高度约束，body 用 flex column + minHeight:0 提供全高滚动区。
// 品牌投影（add-harness-brand-projection 3.1）：harness 取自时间轴 run 节点
// meta（run_metrics 旁路行透出），经 HarnessBrandProvider 注入对话 pane——
// 缺失/未知值走回退链（2026-10-29 用户定稿：缺失 → 中性「AI Assistant」/
// 首字母徽标；未注册值 → 首字母徽标）。
// 主题跟随（2026-11-25 二轮验收用户指令）：撤亮锁壳，壳随根 ConfigProvider
// 双档；pane 深档经 claude-msg-portal 变量组深档覆盖（global.less）。portal
// 挂载点无法继承 .claude-msg-pane 变量——内容根挂 .claude-msg-portal 显式
// 注入（浅/深两组，global.less）。
import { Modal } from 'antd';
import { useIntl } from '@umijs/max';
import { useDshPalette, useThemeScheme } from '@/utils/themeHooks';
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
  const intl = useIntl();
  const pal = useDshPalette();
  const scheme = useThemeScheme();
  return (
    <Modal
      title={intl.formatMessage({ id: 'projects.runRecord.title' }, { runId: runId ?? '' })}
      open={!!runId}
      onCancel={onClose}
      destroyOnHidden
      footer={null}
      width={MAXIMIZED_WIDTH}
      style={MAXIMIZED_MODAL_STYLE}
      styles={{ body: { height: maximizedBodyHeight(), display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
    >
      {/* 二轮验收（2026-11-25 用户指令「运行记录跟随主题」）：撤亮锁——壳随根
          ConfigProvider 双档（深档 darkAlgorithm 深壳），pane 深档经
          claude-msg-portal 变量组深档覆盖；边/底走 pal 双档，浅档字节不变 */}
      <div className="claude-msg-portal" style={{ flex: 1, minHeight: 0, overflow: 'auto', border: `1px solid ${pal.border}`, borderRadius: 8, padding: 8, background: scheme === 'dark' ? 'transparent' : '#fafafa' }}>
        {runId && (
          <HarnessBrandProvider harness={harness}>
            <ClaudeOutputPane key={runId} runId={runId} project={project} />
          </HarnessBrandProvider>
        )}
      </div>
    </Modal>
  );
}
