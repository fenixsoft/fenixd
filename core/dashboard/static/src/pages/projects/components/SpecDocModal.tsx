import { Modal, Tabs, Spin, Empty, Alert, Button } from 'antd';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSpecDoc } from '@/services/dashboard';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';
import { markdownComponents } from '@/components/markdown-shared';

// markdown 映射与链接兜底下沉到 components/markdown-shared（code-review item
// 54951d20a40d）：消费方横跨页面层与共享组件层，共享层不得反向依赖 pages；
// 此处 re-export 保持既有 import 路径（帮助中心 isPageAnchor、KnowledgeTab
// SafeLink 等）不变
export { isPageAnchor, SafeLink, markdownComponents } from '@/components/markdown-shared';

export type DocType = 'proposal' | 'design' | 'tasks' | 'verification' | 'scenarios';

type DocStatus = 'loading' | 'done' | 'empty' | 'error';

interface DocCacheEntry {
  status: DocStatus;
  content?: string;
}

// 文档缓存条目上限：超出后按最旧淘汰，避免长会话跨 spec 浏览时大文本（验证报告/tasks 等）持续累积
const MAX_CACHE_ENTRIES = 50;

// 写入缓存并淘汰超限旧条目；先删后写以刷新该键的新近度（Map 迭代按插入序）。
// reqSeq 为各 key 的请求序号表：淘汰缓存条目时同步删号，避免其条目随长会话
// 跨 spec 浏览无界增长（28af22dbcfe5）；序号全局单调发放、不复用（见
// keyReqSeqRef 声明处），删号不会令陈旧在途请求被误判为最新
const setCacheEntry = (
  cache: Map<string, DocCacheEntry>,
  key: string,
  entry: DocCacheEntry,
  reqSeq: Map<string, number>,
) => {
  cache.delete(key);
  cache.set(key, entry);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined || oldest === key) break;
    cache.delete(oldest);
    reqSeq.delete(oldest);
  }
};

// 缓存键拼接的单一来源：`${project}:${spec}:${doc}`。
// 读写（useMemo 取条目 / loadDoc 写入 / handleRetry 清除）必须共用本函数，
// 口径不一致时读写键错开会导致文档永远停在 Spin 态且无报错
const buildCacheKey = (project: string, spec: string, doc: string) => `${project}:${spec}:${doc}`;

interface SpecDocModalProps {
  project: string;
  spec: string | null;
  open: boolean;
  onClose: () => void;
  // 打开时定位的页签（如时间轴「verification report」链接 → 验证报告）；不传则保持上次页签
  initialDoc?: DocType;
}


export default function SpecDocModal({ project, spec, open, onClose, initialDoc }: SpecDocModalProps) {
  const [activeTab, setActiveTab] = useState<DocType>('proposal');

  // 指定 initialDoc 时，每次打开定位到该页签（验证报告链接入口）。
  // 在渲染期同步改写而非用 effect 定位（code-review item be76833a695a）：
  // effect 定位晚文档加载 effect 一拍，open 翻真的同一轮提交里 loadDoc 仍以
  // 旧 activeTab 先发一次冗余请求、下一轮才按目标页签重发；渲染期改写 state
  // 会在提交前立即重渲染，首次提交即为目标页签，加载只发目标页签一个请求
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open && initialDoc) setActiveTab(initialDoc);
  }
  const { modalProps, maximizeButton, isFullscreen } = useMaximizeModal({
    defaultWidth: '80%',
    defaultBodyHeight: 'calc(80vh - 80px)',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', overflow: 'hidden' },
    centered: true,
  });
  const cacheRef = useRef<Map<string, DocCacheEntry>>(new Map());
  const [cacheVersion, setCacheVersion] = useState(0);
  // 各 key 的请求发起序号（code-review item 9cd221db03d7）：done 态的
  // revalidate 既不写 loading 占位也无在途去重，快速切页签离开再回到同一文档
  // 会同时挂起多个 revalidate 请求，后发先至时旧响应会把较新结果覆盖回陈旧
  // 内容（如旧请求 found=false 把仍在展示的文档打成「无此文档」）。序号由
  // reqSeqCounterRef 全局单调发放、不复用（而非每 key 从 0 重计），await 返回
  // 后复核，仅最新一次请求可写缓存；loading 占位路径的既有「loading 即跳过」
  // 去重不受影响（早退不取新号，不作废在途请求）。条目随缓存淘汰同步清理
  // （见 setCacheEntry，code-review item 28af22dbcfe5），Map 不随长会话无界
  // 增长；也正因 ID 不复用，删号后旧在途请求不会被误判为最新
  const keyReqSeqRef = useRef<Map<string, number>>(new Map());
  const reqSeqCounterRef = useRef(0);

  // 当前 project+spec+doc 的缓存键（含 project 维度：组件跨项目常驻挂载，cacheRef 存活，
  // 不同项目的同名 spec 必须各自独立，避免互相串用文档内容）
  const cacheKey = useMemo(() => {
    if (!spec) return '';
    return buildCacheKey(project, spec, activeTab);
  }, [project, spec, activeTab]);

  // 当前缓存条目
  const currentEntry = useMemo(() => {
    if (!cacheKey) return undefined;
    return cacheRef.current.get(cacheKey);
  }, [cacheKey, cacheVersion]);

  const loadDoc = useCallback(async () => {
    if (!spec) return;
    const key = buildCacheKey(project, spec, activeTab);

    // 检查缓存：loading 表示该 key 已有在途请求，不重复加载
    const cached = cacheRef.current.get(key);
    if (cached && cached.status === 'loading') {
      return;
    }

    // done 缓存仅作首屏占位：文档（验证报告/任务清单等）可能已渐进更新，后台 revalidate 后替换展示
    const revalidate = cached?.status === 'done';

    if (!revalidate) {
      // 设置 loading 状态
      setCacheEntry(cacheRef.current, key, { status: 'loading' }, keyReqSeqRef.current);
      setCacheVersion((v) => v + 1);
    }

    // 发起序号（9cd221db03d7）：同 key 旧请求晚到按过期丢弃，不写缓存
    reqSeqCounterRef.current += 1;
    const requestId = reqSeqCounterRef.current;
    keyReqSeqRef.current.set(key, requestId);

    try {
      const d = await getSpecDoc(project, spec, activeTab);
      if (requestId !== keyReqSeqRef.current.get(key)) return; // 过期响应丢弃
      if (d.found) {
        setCacheEntry(cacheRef.current, key, { status: 'done', content: d.content || '' }, keyReqSeqRef.current);
      } else {
        setCacheEntry(cacheRef.current, key, { status: 'empty' }, keyReqSeqRef.current);
      }
    } catch {
      // revalidate 失败时保留旧内容，避免清空已展示文档
      if (requestId !== keyReqSeqRef.current.get(key)) return; // 过期响应丢弃
      if (!revalidate) {
        setCacheEntry(cacheRef.current, key, { status: 'error' }, keyReqSeqRef.current);
      }
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
    const key = buildCacheKey(project, spec, activeTab);
    cacheRef.current.delete(key);
    void loadDoc();
  }, [project, spec, activeTab, loadDoc]);

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
        <MaximizeTitle
          text={`${spec || ''} 文档`}
          button={maximizeButton}
          isFullscreen={isFullscreen}
        />
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
