import { Button, Input, Modal, Typography, message } from 'antd';
import { useState } from 'react';
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
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);
  const open = !!runId;

  const handleCancel = async () => {
    if (!runId) return;
    setSending(true);
    try {
      await cancelRun(project, runId, reason.trim() || undefined);
      message.success('取消请求已受理，运行将在下一次轮询被终止');
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
        message.info('已有进行中的取消请求，请等待受理');
      } else {
        message.error(`取消失败：${msg}`);
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      title="终止运行"
      open={open}
      onCancel={onClose}
      onOk={() => void handleCancel()}
      okText="确认终止"
      okButtonProps={{ danger: true, loading: sending }}
      cancelText="取消"
      destroyOnHidden
      afterOpenChange={(visible) => { if (visible) setReason(''); }}
    >
      <div style={{ marginBottom: 12 }}>
        <Text>
          即将终止运行 <Text code strong>{runId}</Text>
        </Text>
      </div>
      <div style={{ marginBottom: 4 }}>
        <Text type="secondary">终止原因（可选）：</Text>
      </div>
      <Input.TextArea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="如：空转烧 token、跑错方向…"
        rows={2}
        maxLength={200}
      />
    </Modal>
  );
}
