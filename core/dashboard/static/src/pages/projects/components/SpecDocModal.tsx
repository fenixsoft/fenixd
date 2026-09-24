import { Modal, Tabs, Spin, Empty, Alert, Button } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { getSpecDoc } from '@/services/dashboard';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

export type DocType = 'proposal' | 'design' | 'tasks' | 'verification' | 'scenarios';

type DocStatus = 'loading' | 'done' | 'empty' | 'error';

interface DocCacheEntry {
  status: DocStatus;
  content?: string;
}

interface SpecDocModalProps {
  project: string;
  spec: string | null;
  open: boolean;
  onClose: () => void;
  // 打开时定位的页签（如时间轴「verification report」链接 → 验证报告）；不传则保持上次页签
  initialDoc?: DocType;
}

// 允许的链接协议白名单
const ALLOWED_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

// 自定义链接组件：非白名单协议不输出可点击链接
const SafeLink: Components['a'] = ({ href, children, ...props }) => {
  if (!href) {
    return <span>{children}</span>;
  }

  try {
    const url = new URL(href);
    if (ALLOWED_PROTOCOLS.has(url.protocol)) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    }
  } catch {
    // 无效 URL，作为纯文本处理
  }

  // 非白名单协议或无效 URL，渲染为纯文本
  return <span>{children}</span>;
};

// 自定义 components 配置（验证结论等其它 markdown 场景复用）
// 标题/正文/列表显式定字号，覆盖容器继承（容器多为 13px）
export const markdownComponents: Components = {
  a: SafeLink,
  h1: ({ children }) => <h1 style={{ fontSize: 18, fontWeight: 600 }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: 16, fontWeight: 600 }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: 14, fontWeight: 600 }}>{children}</h3>,
  h4: ({ children }) => <h4 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h4>,
  h5: ({ children }) => <h5 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h5>,
  h6: ({ children }) => <h6 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h6>,
  p: ({ children }) => <p style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</p>,
  ul: ({ children }) => <ul style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</ol>,
  // antd reset 去掉了表格默认边框，这里补齐：通宽 + 灰色细线网格
  table: ({ children, ...props }) => (
    <table style={{ width: '100%', borderCollapse: 'collapse', margin: '12px 0' }} {...props}>
      {children}
    </table>
  ),
  th: ({ children, ...props }) => (
    <th
      style={{ border: '1px solid #e8e8e8', padding: '8px 12px', textAlign: 'left', background: '#fafafa', fontSize: 14 }}
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td style={{ border: '1px solid #e8e8e8', padding: '8px 12px', fontSize: 14 }} {...props}>
      {children}
    </td>
  ),
};

export default function SpecDocModal({ project, spec, open, onClose, initialDoc }: SpecDocModalProps) {
  const [activeTab, setActiveTab] = useState<DocType>('proposal');

  // 指定 initialDoc 时，每次打开定位到该页签（验证报告链接入口）
  useEffect(() => {
    if (open && initialDoc) setActiveTab(initialDoc);
  }, [open, initialDoc]);
  const { modalProps, maximizeButton } = useMaximizeModal({
    defaultWidth: '80%',
    defaultBodyHeight: 'calc(80vh - 80px)',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', overflow: 'hidden' },
    centered: true,
  });
  const cacheRef = useRef<Map<string, DocCacheEntry>>(new Map());
  const [cacheVersion, setCacheVersion] = useState(0);

  // 当前 spec+doc 的缓存键
  const cacheKey = useMemo(() => {
    if (!spec) return '';
    return `${spec}:${activeTab}`;
  }, [spec, activeTab]);

  // 当前缓存条目
  const currentEntry = useMemo(() => {
    if (!cacheKey) return undefined;
    return cacheRef.current.get(cacheKey);
  }, [cacheKey, cacheVersion]);

  const loadDoc = useCallback(async () => {
    if (!spec) return;
    const key = `${spec}:${activeTab}`;

    // 检查缓存，loading/done 不重新加载
    const cached = cacheRef.current.get(key);
    if (cached && (cached.status === 'loading' || cached.status === 'done')) {
      return;
    }

    // 设置 loading 状态
    cacheRef.current.set(key, { status: 'loading' });
    setCacheVersion((v) => v + 1);

    try {
      const d = await getSpecDoc(project, spec, activeTab);
      if (d.found) {
        cacheRef.current.set(key, { status: 'done', content: d.content || '' });
      } else {
        cacheRef.current.set(key, { status: 'empty' });
      }
    } catch {
      cacheRef.current.set(key, { status: 'error' });
    } finally {
      setCacheVersion((v) => v + 1);
    }
  }, [project, spec, activeTab]);

  useEffect(() => {
    if (!open || !spec) return;
    void loadDoc();
  }, [open, spec, loadDoc]);

  // 切换页签时触发加载
  const handleTabChange = useCallback((key: string) => {
    setActiveTab(key as DocType);
  }, []);

  // 重试加载
  const handleRetry = useCallback(() => {
    if (!spec) return;
    const key = `${spec}:${activeTab}`;
    cacheRef.current.delete(key);
    void loadDoc();
  }, [spec, activeTab, loadDoc]);

  const renderContent = () => {
    if (!currentEntry) {
      return (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin />
        </div>
      );
    }

    switch (currentEntry.status) {
      case 'loading':
        return (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <Spin />
          </div>
        );
      case 'empty':
        return <Empty description="无此文档" />;
      case 'error':
        return (
          <Alert
            type="error"
            message="文档加载失败"
            description={
              <Button type="link" onClick={handleRetry}>
                点击重试
              </Button>
            }
          />
        );
      case 'done':
      default:
        return (
          <div
            style={{
              height: '100%',
              overflow: 'auto',
              fontSize: 13,
              lineHeight: 1.65,
            }}
          >
            <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {currentEntry.content || ''}
            </Markdown>
          </div>
        );
    }
  };

  return (
    <Modal
      title={
        <MaximizeTitle text={`${spec || ''} 文档`} button={maximizeButton} />
      }
      open={open}
      onCancel={onClose}
      footer={null}
      {...modalProps}
    >
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          { key: 'proposal', label: '需求背景' },
          { key: 'design', label: '详细设计' },
          { key: 'tasks', label: '任务清单' },
          { key: 'scenarios', label: '测试场景清单' },
          { key: 'verification', label: '验证报告' },
        ]}
      />
      <div style={{ flex: 1, minHeight: 0 }}>{renderContent()}</div>
    </Modal>
  );
}
