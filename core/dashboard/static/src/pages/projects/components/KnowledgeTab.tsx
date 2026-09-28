// KnowledgeTab.tsx — 项目页「项目知识」分面（add-knowledge-atlas 4.1）
//
// 承载知识真相源只读视图：
// - active 门控：仅在选中本分面时拉取 GET /api/knowledge/index，未选中零
//   请求（对齐 QualityTab/RegressionTab/ArchitectureTab 按需加载语义）。
// - enabled 门控：GET /api/config 的 knowledge.enabled === false 时渲染禁用
//   占位（说明 + 去设置页指引），不再发其它请求。
// - 视图栈：总目录（index.md Markdown 渲染 + 域清单 + ADR 列表 + graph 区）
//   → 能力页/导航页/ADR 详情（点进拉单文件，面包屑返回总目录）。
// - graph 区：fetch 探测 /api/knowledge/graph → 200 渲染 <iframe
//   sandbox="allow-scripts">（同 ArchitectureTab 沙箱口径）；404 渲染
//   「关系图尚未生成」占位。
// - 链接导航：Markdown 相对链接（truth-source 内部路径）拦截为站内拉取，
//   经 resolveKnowledgePath 基于当前页目录归一化；外部链接走 SafeLink 白名单。
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnchorHTMLAttributes, FC, ReactNode } from 'react';
import { Breadcrumb, Button, Card, Space, Spin, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ApiError,
  getConfig,
  getKnowledgeFile,
  getKnowledgeIndex,
  knowledgeGraphUrl,
} from '../../../services/dashboard';
import type { KnowledgeIndexData } from '../../../services/dashboard';
import { SafeLink, markdownComponents } from './SpecDocModal';

// SafeLink 的导出类型是 Components['a']（含 undefined/string 字面量宽型），
// 运行时恒为函数组件；此处显式收窄为锚点 FC 供 JSX 复用（实现签名兼容）。
const SafeLinkAsAnchor = SafeLink as FC<
  AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }
>;

interface KnowledgeTabProps {
  project: string;
  active: boolean;
}

// ── 纯函数（node --test 覆盖）────────────────────────────────────────

/** 基于当前页目录归一化真相源内相对链接 → 白名单相对路径；越界/非法返回
 *  null（不发起请求）。currentPath 形如 'domains/pickup/x.md' 或 null（总
 *  目录，基目录为真相源根）。POSIX 语义，不触浏览器 URL。 */
export function resolveKnowledgePath(
  currentPath: string | null,
  href: string,
): string | null {
  if (!href || href.startsWith('#') || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//')) {
    return null;
  }
  const stripped = href.split('#', 1)[0];
  if (!stripped) return null;
  const baseDir = currentPath ? currentPath.replace(/[^/]*$/, '') : '';
  const segments = (baseDir + stripped).split('/');
  const out: string[] = [];
  for (const seg of segments) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      if (out.length === 0) return null; // 越出真相源根
      out.pop();
      continue;
    }
    out.push(seg);
  }
  const resolved = out.join('/');
  if (
    !resolved.startsWith('domains/') &&
    !resolved.startsWith('adr/')
  ) {
    return null;
  }
  return resolved;
}

/** ADR 展示名：'ADR-001-spawn-injection.md' → 'ADR-001 spawn-injection'。 */
export function adrDisplayName(file: string): string {
  const stem = file.replace(/\.md$/, '');
  const m = /^(ADR-\d{3})-(.*)$/.exec(stem);
  return m ? `${m[1]} ${m[2]}` : stem;
}

/** 剥离 Markdown 中的 HTML 注释：marker（capability/rev/sources）是机器
 *  接口，对人类读者隐形（渲染层剥离，源文件不动）。 */
export function stripHtmlComments(md: string): string {
  return md
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** 面包屑：真相源内路径 → 层级显示文本（替代裸目录路径）。
 *  'domains/<域>/<能力>.md' → ['总目录','<域>','<能力>']；
 *  'adr/ADR-001-x.md' → ['总目录','ADR','ADR-001-x']。 */
export function knowledgeCrumbs(path: string): string[] {
  const segs = path
    .replace(/\.md$/, '')
    .split('/')
    .filter(Boolean)
    .filter((s) => s !== '_domain'); // 域导航页：域名本身即当前层级
  if (segs[0] === 'domains') return ['总目录', ...segs.slice(1)];
  if (segs[0] === 'adr') return ['总目录', 'ADR', ...segs.slice(1)];
  return ['总目录', ...segs];
}

/** ADR 列表条目文本：标题字段优先（'ADR-001 <标题>'，编号取自文件名前缀），
 *  无标题回退文件名派生（adrDisplayName）。 */
export function adrListLabel(file: string, title: string | null): string {
  if (title) {
    const m = /^(ADR-\d{3})-/.exec(file.replace(/\.md$/, ''));
    return m ? `${m[1]} ${title}` : title;
  }
  return adrDisplayName(file);
}

// ── 组件 ─────────────────────────────────────────────────────────────

type View =
  | { kind: 'index' }
  | { kind: 'page'; path: string; content: string };

export default function KnowledgeTab({ project, active }: KnowledgeTabProps) {
  const [enabledUnknown, setEnabledUnknown] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [indexData, setIndexData] = useState<KnowledgeIndexData | null>(null);
  const [view, setView] = useState<View>({ kind: 'index' });
  const [loading, setLoading] = useState(false);
  // 加载失败态（code-review item 61d229fbd494）：config/index 请求失败的
  // 错误消息；null = 无错误。与「尚未初始化」业务态区分，不互相伪装。
  const [loadError, setLoadError] = useState<string | null>(null);
  const [graphState, setGraphState] = useState<'unknown' | 'ready' | 'missing'>('unknown');
  // 请求序号守卫（QualityTab/RegressionTab 同款）：慢响应不覆盖新视图
  const seqRef = useRef(0);

  // active 门控拉取：先 config 判 enabled，再 index + graph 探测
  const load = useCallback(async () => {
    if (!active || !project) return;
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      const cfg = await getConfig(project);
      if (seq !== seqRef.current) return;
      const on = cfg.knowledge?.enabled !== false;
      setEnabled(on);
      setEnabledUnknown(false);
      if (!on) return;
      const data = await getKnowledgeIndex(project);
      if (seq !== seqRef.current) return;
      setIndexData(data);
      setLoadError(null);
      // graph 探测：404 = 未生成（占位）；200 = 下发 URL 交 iframe。
      // HEAD 探测（code-review item 6e3bcfab6887）：后端 /api/knowledge/graph
      // 的 GET 路由对 HEAD 同表分派（_handle_api），且 _send_file/_json/_error
      // 均在 command==HEAD 时抑制响应体——探测只收响应头，不再整份下载
      // graph.html；iframe 渲染仍走 GET 的 knowledgeGraphUrl。
      try {
        const res = await fetch(knowledgeGraphUrl(project), { method: 'HEAD' });
        if (seq !== seqRef.current) return;
        setGraphState(res.ok ? 'ready' : 'missing');
      } catch {
        if (seq !== seqRef.current) return;
        setGraphState('missing');
      }
    } catch (e) {
      if (seq !== seqRef.current) return;
      setEnabled(true);
      setEnabledUnknown(false);
      setIndexData(null);
      // 记 error 态而非伪装成「尚未初始化」（code-review item 61d229fbd494）
      setLoadError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [active, project]);

  useEffect(() => {
    if (!active || !project) return;
    void load();
  }, [active, project, load]);

  // 项目切换重置视图态：组件跨项目常驻挂载（Tabs 切换不卸载子组件），
  // 上个项目残留的详情视图（view.kind='page'）会把上个项目的能力页内容
  // 串到新项目显示（冒烟实测）。
  useEffect(() => {
    setView({ kind: 'index' });
    setIndexData(null);
    setGraphState('unknown');
    setEnabledUnknown(true);
    setLoadError(null);
  }, [project]);

  if (!active) return null;

  // ── 禁用占位（knowledge.enabled=false）────────────────────────────
  if (!enabledUnknown && !enabled) {
    return (
      <Card variant="borderless" data-testid="knowledge-disabled-card">
        <Space direction="vertical" size={8}>
          <Typography.Text strong>知识真相源已禁用</Typography.Text>
          <Typography.Text type="secondary" data-testid="knowledge-disabled-desc">
            本实例已在设置中关闭知识真相源（knowledge.enabled=false）。蒸馏管线不会
            运行，此处不展示知识内容；可在「系统设置 → 杂项」中重新开启。
          </Typography.Text>
        </Space>
      </Card>
    );
  }

  if (enabledUnknown || loading) {
    return (
      <Card variant="borderless" data-testid="knowledge-loading">
        <Space>
          <Spin size="small" />
          <Typography.Text type="secondary">加载知识目录…</Typography.Text>
        </Space>
      </Card>
    );
  }

  // 加载失败占位（code-review item 61d229fbd494）：明示错误 + 重试入口，
  // 不再回落到「尚未初始化」业务占位；重试复用 load（loading 态自动接管渲染）。
  if (loadError !== null) {
    return (
      <Card variant="borderless" data-testid="knowledge-load-error">
        <Space direction="vertical" size={8}>
          <Typography.Text strong>知识目录加载失败</Typography.Text>
          <Typography.Text type="secondary">{loadError}</Typography.Text>
          <Button size="small" data-testid="knowledge-retry" onClick={() => void load()}>
            重试
          </Button>
        </Space>
      </Card>
    );
  }

  const uninitialized = !indexData?.initialized;

  const openPage = async (path: string) => {
    const seq = ++seqRef.current;
    try {
      const data = await getKnowledgeFile(project, path);
      if (seq !== seqRef.current) return;
      setView({ kind: 'page', path: data.path, content: data.content });
    } catch (e) {
      if (seq !== seqRef.current) return;
      // 文件缺失等：不置全局 loadError 态，而是整页切换为 page 视图、以引用
      // 块形式提示错误（原视图被替换，可经「返回总目录」回退）
      const msg = e instanceof ApiError ? e.message : String(e);
      setView({ kind: 'page', path, content: `> 加载失败：${msg}\n` });
    }
  };

  // 站内相对链接拦截：真相源内路径 → 站内拉取；其余走 SafeLink 白名单
  const currentPath = view.kind === 'page' ? view.path : null;
  const linkComponents: Components = {
    ...markdownComponents,
    a: (props) => {
      const href = props.href || '';
      const target = resolveKnowledgePath(currentPath, href);
      if (target !== null) {
        return (
          <a
            href={`#knowledge:${target}`}
            onClick={(e) => {
              e.preventDefault();
              void openPage(target);
            }}
          >
            {props.children}
          </a>
        );
      }
      return <SafeLinkAsAnchor {...props} />;
    },
  };

  const openAdrByNumber = (raw: string) => {
    // superseded_by 形如 'ADR-002' 或 'ADR-002(新标题)'——提取编号前缀匹配
    const m = /ADR-\d{3}/.exec(raw);
    if (!m) return;
    const entry = indexData?.adrs.find((a) => a.file.startsWith(`${m[0]}-`));
    if (entry) void openPage(`adr/${entry.file}`);
  };

  const backToIndex = (
    <Button
      size="small"
      data-testid="knowledge-back"
      onClick={() => setView({ kind: 'index' })}
    >
      ← 返回总目录
    </Button>
  );

  // ── 详情视图（能力页 / _domain / ADR 单文件）─────────────────────
  if (view.kind === 'page') {
    return (
      <Card variant="borderless" data-testid="knowledge-page-view">
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space>
            {backToIndex}
            <Breadcrumb
              data-testid="knowledge-page-path"
              items={knowledgeCrumbs(view.path).map((title) => ({ title }))}
            />
          </Space>
          <Markdown remarkPlugins={[remarkGfm]} components={linkComponents}>
            {stripHtmlComments(view.content)}
          </Markdown>
        </Space>
      </Card>
    );
  }

  // ── 总目录视图 ────────────────────────────────────────────────────
  return (
    <Card variant="borderless" data-testid="knowledge-index-view">
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        {uninitialized ? (
          <Typography.Text type="secondary" data-testid="knowledge-uninitialized">
            知识真相源尚未初始化：归档首个 SPEC 后，蒸馏管线会自动在
            spec/knowledge/ 下生成总目录与能力页。
          </Typography.Text>
        ) : (
          <>
            <div data-testid="knowledge-index-md">
              <Markdown remarkPlugins={[remarkGfm]} components={linkComponents}>
                {stripHtmlComments(indexData?.index_md || '')}
              </Markdown>
            </div>

            {/* ADR 列表（状态标签 + superseded 跳转） */}
            {indexData && indexData.adrs.length > 0 ? (
              <div data-testid="knowledge-adr-list">
                <Typography.Text strong>架构决策记录（ADR）</Typography.Text>
                <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
                  {indexData.adrs.map((a) => {
                    const sb = a.superseded_by;
                    return (
                    <li key={a.file} style={{ marginBottom: 4 }}>
                      <a
                        href={`#knowledge:adr/${a.file}`}
                        onClick={(e) => {
                          e.preventDefault();
                          void openPage(`adr/${a.file}`);
                        }}
                      >
                        {adrListLabel(a.file, a.title)}
                      </a>{' '}
                      <Tag color={a.status === 'superseded' ? 'orange' : 'green'}>
                        {a.status}
                      </Tag>
                      {a.status === 'superseded' && sb ? (
                        <a
                          href={`#knowledge:adr:${sb}`}
                          data-testid="knowledge-superseded-link"
                          onClick={(e) => {
                            e.preventDefault();
                            openAdrByNumber(sb);
                          }}
                        >
                          被 {sb} 取代
                        </a>
                      ) : null}
                    </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}

            {/* graph 区：探测 200 → iframe 沙箱；404 → 占位 */}
            <div data-testid="knowledge-graph-section">
              {graphState === 'ready' ? (
                <iframe
                  src={knowledgeGraphUrl(project)}
                  sandbox="allow-scripts"
                  title="知识关系图"
                  style={{ width: '100%', height: 480, border: 0, borderRadius: 8 }}
                />
              ) : (
                <Typography.Text type="secondary" data-testid="knowledge-graph-placeholder">
                  关系图尚未生成
                </Typography.Text>
              )}
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}
