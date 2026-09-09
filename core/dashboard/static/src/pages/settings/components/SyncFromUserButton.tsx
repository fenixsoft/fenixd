import { Button, Modal, message } from 'antd';
import { syncConfigFromUser } from '@/services/dashboard';
import type { ConfigData } from '@/services/dashboard';

// 页标识 → 页签名（确认弹窗文案用），与 settings/index.tsx 菜单 key 对齐
const PAGE_LABELS: Record<string, string> = {
  llm: '模型',
  agents: '模型分配',
  parallel: '并行',
  token: '预算',
  verify: '验证',
  approval: '审批',
  misc: '归档',
  system: '系统',
};

interface SyncFromUserButtonProps {
  /** 当前项目名（项目级作用域才渲染本按钮） */
  project: string;
  /** 当前页签标识（决定只同步该页对应的设置键） */
  page: string;
  /** 同步成功后回调（父组件用它回填表单） */
  onSynced: (config: ConfigData) => void;
}

/**
 * 「同步用户级设置」按钮（白色底，保存按钮左侧）：把用户级 config.yaml 中
 * 当前页签对应的设置值覆盖写入项目级。覆盖前 Modal 确认；只覆盖当前页面
 * 的设置值（后端 _SYNC_PAGE_KEYS 白名单），其它页签与项目级特有键不受影响。
 */
export default function SyncFromUserButton({ project, page, onSynced }: SyncFromUserButtonProps) {
  const pageLabel = PAGE_LABELS[page] ?? page;

  const handleClick = () => {
    Modal.confirm({
      title: '同步用户级设置',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认把用户级的「${pageLabel}」设置覆盖到项目「${project}」？\n\n`}
          仅覆盖本页签对应的设置项，项目级其它设置不受影响；覆盖后立即生效写盘。
        </div>
      ),
      okText: '覆盖',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const config = await syncConfigFromUser(project, page);
          message.success(`已同步用户级「${pageLabel}」设置到项目「${project}」`);
          onSynced(config);
        } catch (err) {
          message.error(`同步失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  return (
    <Button onClick={handleClick} data-testid={`sync-from-user-btn-${page}`}>
      同步用户级设置
    </Button>
  );
}

// 页签底部操作行的统一布局：左=同步用户级设置（项目级显示），右=保存。
// 面板各自的保存按钮行引用此样式，保持八个页签视觉一致。
export const SETTINGS_ACTIONS_ROW_STYLE: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  marginTop: 24,
};
