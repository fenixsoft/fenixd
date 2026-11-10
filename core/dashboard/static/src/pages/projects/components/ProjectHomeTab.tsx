// ProjectHomeTab.tsx — 项目页「项目首页」分面（add-project-home-tab）
//
// 仿 GitHub 项目页形态的只读文件浏览（UI 真相源
// spec/changes/add-project-home-tab/prototype/index.html，逐区块对照）：
// 工具栏（分支 Select 单值只读）→ 根目录最近提交条 → 面包屑（根=项目名）→
// 文件表格（名称/最近提交信息/最近提交时间三列，窄屏仅名称列）→
// 文件内容盒（打开文件时，替代 README 盒位置）/ README 渲染盒（根目录）。
//
// 数据纪律：
// - active 门控：仅选中本分面发首次列表请求（对齐 QualityTab/KnowledgeTab
//   按需加载语义），未选中零请求；切离后在飞结果经 cancelled 闭包静默丢弃
//   （不报错弹窗）。
// - 进程内缓存：同 path 的列表/内容结果入 useRef Map（组件卸载即弃），
//   回分面/往返目录不重复请求。
// - 浏览位置持久化：initialPath 为 URL `?path=` 挂载初值（list.tsx 持有），
//   页内导航经 onNavigate 上行走 replace 写回；直达 path 先按目录探测，
//   404 回退父目录列表 + 条目命中为文件 → 内容视图（文件形态直达）。
// - Markdown 管线复用 react-markdown + markdownComponents 安全渲染族
//   （与 SpecDocModal 同源，SafeLink 协议白名单），MUST NOT 新写管线。
import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Avatar,
  Breadcrumb,
  Button,
  Empty,
  Select,
  Space,
  Spin,
  Table,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import { FileOutlined, FolderOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ApiError,
  fetchProjectFileContent,
  fetchProjectFileDownloadUrl,
  fetchProjectFileList,
} from '@/services/dashboard';
import type {
  ProjectFileContentData,
  ProjectFileEntry,
  ProjectFilesListData,
} from '@/services/dashboard';
import { markdownComponents } from '@/components/markdown-shared';
import { useIsMobile } from '@/hooks/useIsMobile';
import {
  DSH_BG_SOFT,
  DSH_BORDER_SECONDARY,
  DSH_SPLIT,
  DSH_TEXT_SECONDARY,
  DSH_TEXT_TERTIARY,
} from '@/theme';
import {
  formatBytes,
  formatRelativeTime,
  homeCrumbs,
  parseHomePath,
  splitHomePath,
} from './projectHomeShared';

// remarkPlugins 提为模块级常量（对齐 KnowledgeTab KNOWLEDGE_REMARK_PLUGINS
// 先例）：内联数组每次渲染新建引用会让 react-markdown 重新 parse。
const HOME_REMARK_PLUGINS = [remarkGfm];

const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

interface ProjectHomeTabProps {
  project: string;
  active: boolean;
  /** URL `?path=` 的挂载初值（list.tsx 持有持久化；仅挂载时消费一次）。 */
  initialPath: string;
  /** 浏览位置上行（list.tsx replace 写回 URL；根目录传空串）。 */
  onNavigate: (path: string) => void;
}

export default function ProjectHomeTab({
  project,
  active,
  initialPath,
  onNavigate,
}: ProjectHomeTabProps) {
  const isMobile = useIsMobile();

  // 当前目录（仓库根相对路径，'' = 根）与打开的文件（当前目录下文件名）
  const [dir, setDir] = useState('');
  const [file, setFile] = useState<string | null>(null);
  const [dirData, setDirData] = useState<ProjectFilesListData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fileData, setFileData] = useState<ProjectFileContentData | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState('');
  const [readmeData, setReadmeData] = useState<ProjectFileContentData | null>(null);

  // 进程内缓存（组件卸载即弃，useRef 随实例生命周期）：列表按目录 path、
  // 内容按文件 path（README 以文件名同键复用内容缓存）
  const listCacheRef = useRef<Map<string, ProjectFilesListData>>(new Map());
  const contentCacheRef = useRef<Map<string, ProjectFileContentData>>(new Map());

  // initialPath 直达解析只做一次（挂载初值快照）：空串视为无 seed（常规根
  // 目录加载）；非空在首次激活时先按目录探测、404 回退父目录 + 文件命中
  const seedRef = useRef<string | null>(parseHomePath(initialPath) || null);

  const filePath = file === null ? null : dir ? `${dir}/${file}` : file;

  // ── 目录列表加载（active + dir 双门控；缓存命中免请求）──────────────
  // active=false 时零请求；切离分面触发本 effect cleanup（cancelled=true），
  // 在飞响应落地前被静默丢弃。
  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const loadDir = async (target: string) => {
      setError('');
      setLoading(true);
      const cached = listCacheRef.current.get(target);
      if (cached) {
        setDirData(cached);
        setLoading(false);
        return;
      }
      try {
        const d = await fetchProjectFileList(project, target);
        if (cancelled) return;
        listCacheRef.current.set(target, d);
        setDirData(d);
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? '路径不存在，可能已被移动或删除'
            : e instanceof ApiError
              ? e.message
              : '加载失败',
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    // 首次激活的直达解析：非空 seed 先按目录探测，list 404（文件路径不经
    // 列表通道）回退父目录列表 + 条目命中为文件 → 内容视图。父目录列表与
    // 文件内容均先入缓存，随后的常规 effect 轮从缓存命中免重拉。
    const seed = seedRef.current;
    seedRef.current = null;
    if (seed !== null) {
      setLoading(true);
      void (async () => {
        try {
          const d = await fetchProjectFileList(project, seed);
          if (cancelled) return;
          listCacheRef.current.set(seed, d);
          setDir(seed);
          return;
        } catch {
          /* 非目录 → 文件形态回退探测 */
        }
        if (cancelled) return;
        const { dir: parent, name } = splitHomePath(seed);
        try {
          const pd = await fetchProjectFileList(project, parent);
          if (cancelled) return;
          listCacheRef.current.set(parent, pd);
          setDir(parent);
          if (pd.entries.some((en) => en.name === name && !en.dir)) {
            setFile(name);
            try {
              const c = await fetchProjectFileContent(project, seed);
              if (!cancelled) contentCacheRef.current.set(seed, c);
            } catch {
              if (!cancelled) setFileError('文件内容加载失败');
            }
          } else {
            setError('路径不存在');
          }
        } catch {
          if (!cancelled) setError('路径不存在');
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
      return () => {
        cancelled = true;
      };
    }

    void loadDir(dir);
    return () => {
      cancelled = true;
    };
  }, [active, dir, project]);

  // ── 文件内容加载（打开文件时；缓存命中免请求）───────────────────────
  useEffect(() => {
    if (filePath === null || !active) return;
    const cached = contentCacheRef.current.get(filePath);
    if (cached) {
      setFileData(cached);
      return;
    }
    let cancelled = false;
    setFileError('');
    setFileLoading(true);
    fetchProjectFileContent(project, filePath)
      .then((c) => {
        if (cancelled) return;
        contentCacheRef.current.set(filePath, c);
        setFileData(c);
      })
      .catch((e) => {
        if (cancelled) return;
        setFileError(e instanceof ApiError ? e.message : '文件内容加载失败');
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filePath, active, project]);

  // ── README 加载（根目录且未打开文件时按 readme 字段拉内容通道）───────
  // 拉取失败静默降级为不渲染 README 盒（无 README 项目不渲染空盒的边界延伸）。
  const readmeName = dir === '' && file === null ? dirData?.readme ?? null : null;
  useEffect(() => {
    if (!readmeName || !active) return;
    const cached = contentCacheRef.current.get(readmeName);
    if (cached) {
      setReadmeData(cached);
      return;
    }
    let cancelled = false;
    setReadmeData(null);
    fetchProjectFileContent(project, readmeName)
      .then((c) => {
        if (cancelled) return;
        contentCacheRef.current.set(readmeName, c);
        setReadmeData(c);
      })
      .catch(() => {
        if (!cancelled) setReadmeData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [readmeName, active, project]);

  // ── 导航动作（原地更新列表，不整页刷新、不改路由路径）───────────────
  const openDir = (name: string) => {
    const next = dir ? `${dir}/${name}` : name;
    setFile(null);
    setFileData(null);
    setFileError('');
    setDir(next);
    onNavigate(next);
  };
  const openFile = (name: string) => {
    setFile(name);
    setFileData(null);
    setFileError('');
    onNavigate(dir ? `${dir}/${name}` : name);
  };
  /** 面包屑回退：depth=0 回根目录，n 回前 n 段目录。 */
  const goDepth = (depth: number) => {
    const next = homeCrumbs(dir).slice(0, depth).join('/');
    setFile(null);
    setFileData(null);
    setFileError('');
    setDir(next);
    onNavigate(next);
  };

  // ── 文件表格（三列；窄屏 <768px 仅名称列）──────────────────────────
  const columns: TableProps<ProjectFileEntry>['columns'] = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: false,
      render: (_v, r) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {r.dir ? (
            <FolderOutlined style={{ color: DSH_TEXT_TERTIARY, flex: 'none' }} />
          ) : (
            <FileOutlined style={{ color: DSH_TEXT_TERTIARY, flex: 'none' }} />
          )}
          <span style={{ fontSize: 14 }}>{r.name}</span>
        </span>
      ),
    },
    {
      title: '最近提交信息',
      dataIndex: ['last_commit', 'message'],
      key: 'msg',
      ellipsis: true,
      hidden: isMobile,
      render: (v: string | undefined) => (
        <span style={{ color: DSH_TEXT_SECONDARY, fontSize: 13 }}>{v || '—'}</span>
      ),
    },
    {
      title: '最近提交时间',
      dataIndex: ['last_commit', 'time'],
      key: 'time',
      hidden: isMobile,
      width: 128,
      render: (v: string | undefined) => (
        <span
          style={{
            display: 'block',
            textAlign: 'right',
            color: DSH_TEXT_TERTIARY,
            fontSize: 13,
            whiteSpace: 'nowrap',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {v ? formatRelativeTime(v) : '—'}
        </span>
      ),
    },
  ];

  const crumbs = homeCrumbs(dir);
  const atRoot = dir === '' && file === null;
  const latest = atRoot ? dirData?.latest ?? null : null;
  const nonGit = dirData?.non_git === true;

  if (nonGit) {
    // 非 git 项目空态：Empty + 中文说明，不报错弹窗、不渲染破损列表
    return (
      <Empty
        data-testid="project-home-empty"
        description="该项目不是 git 仓库或暂无提交历史"
        style={{ padding: '56px 0' }}
      />
    );
  }

  return (
    <div data-testid="project-home-panel">
      <div
        data-testid="project-home-filetable"
        style={{
          border: `1px solid ${DSH_BORDER_SECONDARY}`,
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        {/* 工具栏：分支 Select 仅渲染当前分支单选项（detached 显示短 hash），
            不提供切换（本期边界；原型中分支/标签为假数据演示，不落实现） */}
        <div
          data-testid="project-home-toolbar"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '10px 16px',
            borderBottom: `1px solid ${DSH_SPLIT}`,
            flexWrap: 'wrap',
          }}
        >
          <Space size={12} wrap>
            <Select
              size="small"
              style={{ width: 150 }}
              value={dirData?.branch ?? undefined}
              options={
                dirData?.branch ? [{ value: dirData.branch, label: dirData.branch }] : []
              }
            />
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            只读浏览 · 点击文件夹进入子目录，点击文件查看内容
          </Typography.Text>
        </div>

        {/* 根目录最近提交条（作者 / 短 hash / 相对时间；打开文件时不渲染） */}
        {latest && (
          <div
            data-testid="project-home-latest-commit"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
            }}
          >
            <Avatar
              size={24}
              style={{
                backgroundColor: DSH_BG_SOFT,
                color: DSH_TEXT_SECONDARY,
                border: `1px solid ${DSH_BORDER_SECONDARY}`,
                fontSize: 12,
                flex: 'none',
              }}
            >
              {(latest.author || '?').slice(0, 1)}
            </Avatar>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{latest.author}</span>
            <span
              style={{
                fontFamily: MONO_FONT,
                fontSize: 12,
                color: DSH_TEXT_SECONDARY,
                background: DSH_BG_SOFT,
                border: `1px solid ${DSH_BORDER_SECONDARY}`,
                borderRadius: 4,
                padding: '1px 6px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {latest.hash}
            </span>
            <span
              style={{
                marginLeft: 'auto',
                color: DSH_TEXT_TERTIARY,
                fontSize: 12,
                whiteSpace: 'nowrap',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {formatRelativeTime(latest.time)}
            </span>
          </div>
        )}

        {/* 面包屑（根=项目名；文件视图末段为文件名） */}
        <div
          data-testid="project-home-breadcrumb"
          style={{
            padding: '8px 16px',
            borderBottom: `1px solid ${DSH_SPLIT}`,
            fontSize: 14,
          }}
        >
          {crumbs.length === 0 && file === null ? (
            <span style={{ fontWeight: 600 }}>{project}</span>
          ) : (
            <Breadcrumb
              items={[
                {
                  title: (
                    <a
                      onClick={(e) => {
                        e.preventDefault();
                        goDepth(0);
                      }}
                    >
                      {project}
                    </a>
                  ),
                },
                ...crumbs.map((seg, i) => ({
                  title:
                    i === crumbs.length - 1 && file === null ? (
                      <span style={{ fontWeight: 600 }}>{seg}</span>
                    ) : (
                      <a
                        onClick={(e) => {
                          e.preventDefault();
                          goDepth(i + 1);
                        }}
                      >
                        {seg}
                      </a>
                    ),
                })),
                ...(file ? [{ title: <span style={{ fontWeight: 600 }}>{file}</span> }] : []),
              ]}
            />
          )}
        </div>

        {error ? (
          <Alert type="warning" showIcon message={error} style={{ margin: '12px 16px' }} />
        ) : (
          <Table<ProjectFileEntry>
            size="middle"
            loading={loading}
            pagination={false}
            columns={columns}
            dataSource={(dirData?.entries ?? []).map((e) => ({ ...e, key: e.name }))}
            onRow={(r) => ({
              onClick: () => (r.dir ? openDir(r.name) : openFile(r.name)),
              style: { cursor: 'pointer' },
            })}
          />
        )}

        {/* 目录条目截断提示（超 200 项；spec「如『仅展示前 200 项』」） */}
        {!!dirData?.truncated_count && (
          <div
            style={{
              padding: '8px 16px',
              borderTop: `1px solid ${DSH_SPLIT}`,
              background: DSH_BG_SOFT,
              color: DSH_TEXT_SECONDARY,
              fontSize: 12,
            }}
          >
            仅展示前 200 项，其余 {dirData.truncated_count} 项已截断
          </div>
        )}
      </div>

      {/* 文件内容盒（打开文件时替代 README 盒位置） */}
      {filePath !== null && (
        <div
          data-testid="project-home-fileview"
          style={{
            border: `1px solid ${DSH_BORDER_SECONDARY}`,
            borderRadius: 8,
            marginTop: 16,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
              background: DSH_BG_SOFT,
              flexWrap: 'wrap',
            }}
          >
            <FileOutlined style={{ color: DSH_TEXT_TERTIARY }} />
            <span style={{ fontSize: 14, fontWeight: 600 }}>{file}</span>
            {fileData && !fileData.binary && (
              <span
                style={{
                  fontSize: 12,
                  color: DSH_TEXT_TERTIARY,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {fileData.lines} 行 · {formatBytes(fileData.bytes)}
              </span>
            )}
            <span style={{ marginLeft: 'auto' }}>
              <Button size="small" href={fetchProjectFileDownloadUrl(project, filePath)} download>
                下载
              </Button>
            </span>
          </div>
          {fileError ? (
            <Alert type="warning" showIcon message={fileError} style={{ margin: 16 }} />
          ) : fileLoading ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Spin />
            </div>
          ) : fileData?.binary ? (
            <div
              style={{
                padding: '40px 16px',
                textAlign: 'center',
                color: DSH_TEXT_TERTIARY,
                fontSize: 13,
              }}
            >
              二进制文件，暂不支持预览
            </div>
          ) : fileData ? (
            <>
              <div style={{ padding: '12px 16px', overflow: 'auto' }}>
                <pre
                  style={{
                    margin: 0,
                    fontFamily: MONO_FONT,
                    fontSize: 13,
                    lineHeight: 1.6,
                    whiteSpace: 'pre',
                  }}
                >
                  {fileData.content}
                </pre>
              </div>
              {fileData.truncated && (
                <div
                  style={{
                    padding: '8px 16px',
                    borderTop: `1px solid ${DSH_SPLIT}`,
                    background: DSH_BG_SOFT,
                    color: DSH_TEXT_SECONDARY,
                    fontSize: 12,
                  }}
                >
                  文件过大，仅展示前 256 KB，下载查看全文
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* README 渲染盒（根目录且未打开文件时；react-markdown 安全管线复用） */}
      {atRoot && readmeData && !readmeData.binary && dirData?.readme && (
        <div
          data-testid="project-home-readme"
          style={{
            border: `1px solid ${DSH_BORDER_SECONDARY}`,
            borderRadius: 8,
            marginTop: 16,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            <FileOutlined style={{ color: DSH_TEXT_TERTIARY }} />
            {dirData.readme}
            <span
              style={{
                marginLeft: 'auto',
                fontWeight: 400,
                color: DSH_TEXT_TERTIARY,
                fontSize: 12,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {formatBytes(readmeData.bytes)}
            </span>
          </div>
          <div style={{ padding: '20px 24px 28px', fontSize: 14, lineHeight: 1.7 }}>
            <Markdown remarkPlugins={HOME_REMARK_PLUGINS} components={markdownComponents}>
              {readmeData.content ?? ''}
            </Markdown>
          </div>
          {readmeData.truncated && (
            <div
              style={{
                padding: '8px 16px',
                borderTop: `1px solid ${DSH_SPLIT}`,
                background: DSH_BG_SOFT,
                color: DSH_TEXT_SECONDARY,
                fontSize: 12,
              }}
            >
              文件过大，仅展示前 256 KB，下载查看全文
            </div>
          )}
        </div>
      )}
    </div>
  );
}
