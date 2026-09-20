import { App, Button } from 'antd';
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
  // 消费 App 上下文（code-review item 633923ee6b0b）：静态 Modal/message 无法
  // 消费 <AntdApp> 上下文，会与 App.useApp() 页面产生主题/locale 不一致并在开发
  // 环境触发 antd 静态方法告警。
  const { message, modal } = App.useApp();
  // 回退不再直接暴露内部 key（code-review item e0b8f3aefec7）
  const pageLabel = PAGE_LABELS[page] ?? '当前页签';

  const handleClick = () => {
    modal.confirm({
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
        let config: ConfigData;
        try {
          config = await syncConfigFromUser(project, page);
          message.success(`已同步用户级「${pageLabel}」设置到项目「${project}」`);
        } catch (err) {
          message.error(`同步失败：${err instanceof Error ? err.message : String(err)}`);
          // 失败时 reject 让弹窗保持打开（用户可直接重试，无需重新打开）
          // （code-review item 689fe8681e9a）
          throw err;
        }
        // 后端已写盘成功，回填回调移出 try（code-review item 689fe8681e9a）：
        // 旧实现把 onSynced 放在同一 try，回调抛错会被误报为「同步失败」。
        try {
          onSynced(config);
        } catch (e) {
          message.warning(`同步成功但刷新失败：${e instanceof Error ? e.message : String(e)}`);
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

// 页签底部操作行的统一布局：右对齐，「同步用户级设置」紧邻「保存」左侧。
// 面板各自的保存按钮行引用此样式，保持八个页签视觉一致。
export const SETTINGS_ACTIONS_ROW_STYLE: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  alignItems: 'center',
  gap: 8,
  marginTop: 24,
};
