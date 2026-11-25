import { App, Button, Input, Modal, Typography } from 'antd';
import { useState } from 'react';
import { useIntl } from '@umijs/max';
import { ApiError, cancelRun } from '@/services/dashboard';

const { Text } = Typography;

interface RunCancelModalProps {
  project: string;
  runId: string | null;
  onClose: () => void;
  /** 受理成功后回调（供调用方在行内展示反馈） */
  onAccepted?: (runId: string) => void;
}

export default function RunCancelModal({ project, runId, onClose, onAccepted }: RunCancelModalProps) {
  const intl = useIntl();
  const { message } = App.useApp();
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);
  const open = !!runId;

  const handleCancel = async () => {
    if (!runId) return;
    setSending(true);
    try {
      await cancelRun(project, runId, reason.trim() || undefined);
      message.success(intl.formatMessage({ id: 'projects.runCancel.successAccepted' }));
      const acceptedRunId = runId;
      setReason('');
      onAccepted?.(acceptedRunId);
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 业务拒绝按稳定错误码分支（code-review item 813aa61cb08f，与
      // QualityTab/RegressionTab 先例同口径）：旧实现对后端文案与状态码做
      // 子串匹配，措辞一改即静默落入通用错误分支；错误码由后端 _coded_error
      // 下发、ApiError.code 承载。
      if (err instanceof ApiError && err.code === 'cancel_run_request_pending') {
        message.info(intl.formatMessage({ id: 'projects.runCancel.pendingInfo' }));
      } else {
        message.error(intl.formatMessage({ id: 'projects.runCancel.failed' }, { msg }));
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      title={intl.formatMessage({ id: 'projects.runCancel.title' })}
      open={open}
      onCancel={onClose}
      // onOk 返回 Promise（code-review item 6ee22cfaf358）：antd 等待其落定并
      // 保持弹窗打开——失败时（handleCancel 内部已 toast 吞错，Promise 恒
      // resolve）已填原因不丢、loading 态可见；成功路径由 handleCancel 自调
      // onClose() 关闭，行为不变。void 形式返回 undefined 会让弹窗瞬时关闭。
      onOk={() => handleCancel()}
      okText={intl.formatMessage({ id: 'projects.runCancel.okText' })}
      okButtonProps={{ danger: true, loading: sending }}
      cancelText={intl.formatMessage({ id: 'projects.runCancel.cancelText' })}
      destroyOnHidden
      afterOpenChange={(visible) => { if (visible) setReason(''); }}
    >
      <div style={{ marginBottom: 12 }}>
        <Text>
          {intl.formatMessage({ id: 'projects.runCancel.willTerminate' })} <Text code strong>{runId}</Text>
        </Text>
      </div>
      <div style={{ marginBottom: 4 }}>
        <Text type="secondary">{intl.formatMessage({ id: 'projects.runCancel.reasonLabel' })}</Text>
      </div>
      <Input.TextArea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={intl.formatMessage({ id: 'projects.runCancel.reasonPlaceholder' })}
        rows={2}
        maxLength={200}
      />
    </Modal>
  );
}
