import { App, Button, Modal } from 'antd';
import { useState } from 'react';
import { syncConfigFromUser } from '@/services/dashboard';
import type { ConfigData } from '@/services/dashboard';

// 页标识 → 页签名：单一来源取 settings/index.tsx 的 BASE_MENU_ITEMS
// （code-review item e0b8f3aefec7：旧实现是手工副本，页签增删/改名会漂移；
// 且 `?? page` 回退会把内部 key 暴露到用户可见弹窗）。此处集中导入并在回退
// 分支给出可控提示而非裸 key。
import { PAGE_LABELS } from '../index';

interface SyncFromUserButtonProps {
  /** 当前项目名（项目级作用域才渲染本按钮） */
  project: string;
  /** 当前页签标识（决定只操作该页对应的设置键） */
  page: string;
  /** 同步/清空成功后回调（父组件用它回填表单） */
  onSynced: (config: ConfigData) => void;
}

/**
 * 「同步用户级设置」按钮（白色底，保存按钮左侧）：把用户级 config.yaml 中
 * 当前页签对应的设置值覆盖写入项目级。确认弹窗提供两个互斥操作——
 * · 覆盖：用户级值写入项目级（同步）；
 * · 清空：删除项目级该页签受管键，此后本项目直接沿用用户级配置/默认值
 *   （项目级不再显式覆盖，sources 回 "user"）。
 * 只影响当前页签的设置值（后端 _SYNC_PAGE_KEYS 白名单），其它页签不受影响。
 *
 * 用受控 Modal 而非 modal.confirm（本组件需同弹窗三按钮 + 独立 loading；
 * 且 JSX 渲染天然消费 <AntdApp> 上下文——code-review item 633923ee6b0b）。
 */
export default function SyncFromUserButton({ project, page, onSynced }: SyncFromUserButtonProps) {
  const { message } = App.useApp();
  // 回退不再直接暴露内部 key（code-review item e0b8f3aefec7）
  const pageLabel = PAGE_LABELS[page] ?? '当前页签';
  const [open, setOpen] = useState(false);
  // 当前进行中的操作（互斥 loading；null = 空闲）
  const [busy, setBusy] = useState<null | 'sync' | 'clear'>(null);

  const runAction = async (action: 'sync' | 'clear') => {
    setBusy(action);
    try {
      const config = await syncConfigFromUser(project, page, action);
      if (action === 'sync') {
        message.success(`已同步用户级「${pageLabel}」设置到项目「${project}」`);
      } else if (config.cleared == null) {
        message.info(`项目级没有「${pageLabel}」的显式设置，无需清空`);
      } else {
        message.success(`已清空项目级「${pageLabel}」设置，现沿用用户级配置`);
      }
      setOpen(false);
      // 后端已写盘成功，回填回调失败不误报为「操作失败」（对齐 code-review
      // item 689fe8681e9a：写盘成功与前端刷新分开报告）
      try {
        onSynced(config);
      } catch (e) {
        message.warning(`操作成功但刷新失败：${e instanceof Error ? e.message : String(e)}`);
      }
    } catch (err) {
      // 失败不关弹窗，用户可直接重试（对齐旧 confirm 行为）
      message.error(
        `${action === 'sync' ? '同步' : '清空'}失败：${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Button onClick={() => setOpen(true)} data-testid={`sync-from-user-btn-${page}`}>
        同步用户级设置
      </Button>
      <Modal
        title="同步用户级设置"
        open={open}
        onCancel={() => setOpen(false)}
        maskClosable={busy === null}
        footer={[
          <Button key="cancel" disabled={busy !== null} onClick={() => setOpen(false)}>
            取消
          </Button>,
          <Button
            key="clear"
            data-testid={`clear-page-config-${page}`}
            loading={busy === 'clear'}
            disabled={busy !== null && busy !== 'clear'}
            onClick={() => runAction('clear')}
          >
            清空
          </Button>,
          <Button
            key="sync"
            type="primary"
            danger
            loading={busy === 'sync'}
            disabled={busy !== null && busy !== 'sync'}
            onClick={() => runAction('sync')}
          >
            覆盖
          </Button>,
        ]}
      >
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`· 覆盖：把用户级「${pageLabel}」设置覆盖写入项目「${project}」。
· 清空：删除项目级「${pageLabel}」设置，此后本项目直接沿用用户级配置（或默认值）。

两者只影响本页签对应的设置项，其它页签与项目级特有键不受影响；操作立即生效写盘。`}
        </div>
      </Modal>
    </>
  );
}

// 页签底部操作行的统一布局：右对齐，「同步用户级设置」紧邻「保存」左侧。
// 面板各自的保存按钮行引用此样式，保持八个页签视觉一致。
export const SETTINGS_ACTIONS_ROW_STYLE: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  alignItems: 'center',
  gap: 8,
  marginTop: 24,
};
