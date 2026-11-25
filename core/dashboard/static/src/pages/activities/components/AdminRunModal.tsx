import { ConfigProvider, Modal, theme } from 'antd';
import { useEffect, useState } from 'react';
import { ClaudeOutputPane, HarnessBrandProvider } from '@/components/claude-msg';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

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
    <ConfigProvider
      // 亮锁壳（2026-11-25 深色档验收，对齐 RunRecordModal）：内容树亮色设计，
      // 深色宿主下以亮色算法+白底种子隔离，浅色宿主幂等；壳（标题栏/关闭钮）
      // 一并亮锁，避免深壳亮身割裂
      theme={{ algorithm: theme.defaultAlgorithm, token: { colorBgBase: '#ffffff' } }}
    >
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
          isFullscreen={isFullscreen}
        />
      }
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      {...modalProps}
      // 壳显式亮锁（2026-11-25 验收兜底层，对齐 RunRecordModal）：嵌套
      // ConfigProvider 亮色算法到不了 Modal portal，chrome 四键直接定死亮值；
      // 必须放在 {...modalProps} 之后（其 styles.body 为最大化几何，保留合并）
      styles={{
        ...modalProps.styles,
        container: { background: '#ffffff' },
        header: { background: '#ffffff' },
        // title/close 取 antd 浅档 token 缺省字节（colorTextHeading/.45 三级字），
        // 浅色宿主逐字节不变；深色宿主下此弹窗本就亮锁
        title: { color: 'rgba(0, 0, 0, 0.88)' },
        close: { color: 'rgba(0, 0, 0, 0.45)' },
      }}
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
        className="claude-msg-portal"
      >
        <HarnessBrandProvider harness={harness}>
          <ClaudeOutputPane
            runId={adminRunId}
            project={project}
            onEventsCount={setEventCount}
            waitingText="Administrator 已唤起"
          />
        </HarnessBrandProvider>
      </div>
    </Modal>
    </ConfigProvider>
  );
}
