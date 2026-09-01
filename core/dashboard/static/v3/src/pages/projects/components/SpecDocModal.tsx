import { Modal, Tabs, Spin, Empty, Alert, Button } from 'antd';
import { FullscreenExitOutlined, FullscreenOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { getSpecDoc } from '@/services/dashboard';

type DocType = 'proposal' | 'design' | 'tasks';

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

// 自定义 components 配置
const markdownComponents: Components = {
  a: SafeLink,
};

export default function SpecDocModal({ project, spec, open, onClose }: SpecDocModalProps) {
  const [activeTab, setActiveTab] = useState<DocType>('proposal');
  const [maximized, setMaximized] = useState(false);
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

  // 默认尺寸 = 视口宽高的 80%；最大化 = 占满全屏
  const modalWidth = maximized ? '100vw' : '80%';
  const bodyHeight = maximized ? 'calc(100vh - 80px)' : 'calc(80vh - 80px)';

  return (
    <Modal
      title={
        // 最大化按钮绝对定位到关闭按钮左侧（关闭按钮为绝对定位，占 modal 右缘 12~44px）
        <div style={{ position: 'relative' }}>
          <span>{`${spec || ''} 文档`}</span>
          <Button
            type="text"
            size="small"
            title={maximized ? '还原' : '最大化'}
            icon={maximized ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            onClick={() => setMaximized((v) => !v)}
            style={{ position: 'absolute', right: 24, top: 8 }}
          />
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={modalWidth}
      centered={!maximized}
      style={maximized ? { top: 0, maxWidth: '100vw', paddingBottom: 0 } : undefined}
      styles={{ body: { height: bodyHeight, display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
    >
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          { key: 'proposal', label: '需求背景' },
          { key: 'design', label: '详细设计' },
          { key: 'tasks', label: '任务清单' },
        ]}
      />
      <div style={{ flex: 1, minHeight: 0 }}>{renderContent()}</div>
    </Modal>
  );
}
