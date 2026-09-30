import { Alert, App, Button, Card, Input, Popconfirm, Typography } from 'antd';
import { useState, useEffect, useRef } from 'react';
import type { ConfigData } from '@/services/dashboard';
// 切页签/作用域丢弃确认的判脏登记（code-review item 8a3eb01dc2b9）
import { usePanelDirty } from '../panelDirty';
import {
  autodraftVerifyYaml,
  getVerifyYaml,
  getVerifyYamlTemplate,
  regenerateProjectDescription,
  saveVerifyYaml,
} from '@/services/dashboard';

const { TextArea } = Input;
const { Text } = Typography;

interface ProjectProfilePanelProps {
  config: ConfigData;
  /** 父级 handleSave 契约：保存失败时 toast 错误后返回 false（不抛异常），
   *  true 才算落盘成功——调用方必须按返回值分支，不得当作必然成功。 */
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  project?: string;
  /** 聚焦信号（时间戳）：质量页签「手工编辑」跳转过来时 >0，滚动定位到
   *  verify.yaml 卡片并聚焦编辑框；常规切页签传 0 不触发 */
  focusVerifySignal?: number;
}

export default function ProjectProfilePanel({ config, onSave, project, focusVerifySignal }: ProjectProfilePanelProps) {
  // 经 App.useApp() 取 message 实例（code-review item 1432cb8853fe）：与其余
  // 设置面板口径一致，静态 message 不经过 App/ConfigProvider 上下文
  const { message } = App.useApp();
  const [description, setDescription] = useState(config.description || '');
  const [loading, setLoading] = useState(false);
  // 简介保存重入守卫：保存请求在飞期间置位，按钮 loading/disabled 阻止连点
  // 并发发多个写同一配置文件的保存请求（对齐 verify.yaml 保存的 yamlSaving 口径）
  const [saving, setSaving] = useState(false);
  // 「手工编辑」跳转定位：ref 指向本实例渲染的卡片/编辑框（不用
  // querySelector——设置页切作用域曾出现双 DOM 实例并存，选择器会命中隐藏实例）
  const verifySectionRef = useRef<HTMLDivElement>(null);
  const yamlTextareaRef = useRef<HTMLTextAreaElement>(null);
  // 简介草稿基线与归属（code-review items b1e4d7434e0e / 30aaaac87fce）：比照
  // yaml 侧 yamlLoadedContentRef/yamlDraftSourceRef 口径——baseline 记录草稿对
  // 应的已保存值（外部回填前比对，防静默覆盖未保存修改），project 记录草稿
  // 归属项目（保存前比对，防切项目窗口把上一项目简介以当前项目名写盘）。
  const descriptionSourceRef = useRef<{ project: string | undefined; baseline: string }>({
    project,
    baseline: config.description || '',
  });

  useEffect(() => {
    const next = config.description || '';
    const src = descriptionSourceRef.current;
    if (src.project !== project) {
      // 切项目后新 config 到达：显式切换动作，直接覆盖上一项目残留草稿
      //（比照 yaml 非静默加载口径），归属随之推进到当前项目
      setDescription(next);
    } else if (description !== next && description !== src.baseline) {
      // 同项目外部刷新（「同步用户级设置」回填、其它面板保存触发的父级
      // setConfig）遇未保存草稿（既不等于服务器新值也不等于基线）：保留
      // 用户编辑不覆盖，仅同步基线并提示（比照 yaml 静默回写保护口径）。
      message.warning('项目配置已刷新，但简介有未保存修改，已保留您的编辑');
    } else {
      setDescription(next);
    }
    descriptionSourceRef.current = { project, baseline: next };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 依赖刻意只有 config：
    // effect 仅在父级 setConfig（config 对象更替）时触发，此刻闭包里的
    // description/project 必与该份 config 配套；补 project 会在切项目首渲染
    //（config 仍是上一项目）用旧值抢跑回填，补 description 则每次键入都重跑
  }, [config]);

  // 聚焦信号到达：滚到 verify.yaml 卡片并把光标送入编辑框（延迟等待页签
  // 切换后本面板真正挂载渲染完成）
  useEffect(() => {
    if (!focusVerifySignal) return;
    verifySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const t = setTimeout(() => {
      const el = yamlTextareaRef.current;
      if (el) {
        el.focus();
        const len = el.value.length;
        try {
          el.setSelectionRange(len, len);
        } catch {
          /* setSelectionRange 对特定 type 可能抛错，聚焦已达成即可 */
        }
      }
    }, 300);
    return () => clearTimeout(t);
  }, [focusVerifySignal]);

  const handleSave = async () => {
    if (saving) return; // 重入守卫：保存请求在飞期间连点直接短路，不发并发保存请求
    // 草稿归属守卫（code-review item 30aaaac87fce）：比照 yaml 侧
    // yamlDraftSourceRef 口径——切项目的 config 加载往返窗口内草稿仍是上一个
    // 项目的简介，此时以当前项目名写盘会覆盖新项目的既有简介——拒绝并提示。
    if (descriptionSourceRef.current.project !== project) {
      message.warning('项目简介尚未随当前项目加载完成（或已切换项目），请稍候再保存');
      return;
    }
    setSaving(true);
    try {
      // 父级保存失败时返回 false（错误 toast 已由父级呈现），仅明确成功才
      // 提示「保存成功」，避免失败时错误与成功两条提示自相矛盾。
      const ok = await onSave({ description });
      if (ok) {
        message.success('保存成功');
        // 已落盘内容即新基线（比照 yaml 侧 d9f2bd1097f0）：保存触发的父级重载
        // 回填到来时，草稿不会误入「未保存修改」保护分支
        descriptionSourceRef.current = { project, baseline: description };
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save description:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    if (!project) {
      message.error('项目名称缺失，无法重新生成');
      return;
    }

    setLoading(true);
    try {
      const result = await regenerateProjectDescription(project);
      // description 为可选字段：空值时视为失败阻断保存，不得以 undefined 回填草稿
      // （比照 PromptsPanel 跨项目错写防护的 data 判空口径）
      if (result.ok && result.description != null) {
        // 先落盘再改本地状态：保存失败（父级返回 false，已由父级 toast）时
        // 不得 setDescription，否则本地简介与服务器漂移且用户无从察觉。
        const saved = await onSave({ description: result.description });
        if (saved) {
          setDescription(result.description);
          // 已落盘内容即新基线（与 handleSave 同口径）：保存触发的父级重载
          // 回填到来时，草稿不会误入「未保存修改」保护分支
          descriptionSourceRef.current = { project, baseline: result.description };
          // 生成成功与保存落盘是两个独立结果，分开提示
          message.success('简介重新生成成功');
          message.success('已保存到项目配置');
        } else {
          message.warning('简介已生成，但保存到项目配置失败，请重试或手动保存');
        }
      } else {
        message.error(result.error || '重新生成失败');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`重新生成失败：${errorMessage}`);
      console.error('Failed to regenerate description:', error);
    } finally {
      setLoading(false);
    }
  };

  // ── verify.yaml 查看与编辑（项目级文件）──
  const [yamlDraft, setYamlDraft] = useState<string>('');
  const [yamlExists, setYamlExists] = useState<boolean>(false);
  // 加载失败独立标记：yamlExists 只在加载成功时更新，失败时保持旧值 false 会把
  // 「加载失败」误呈现为「确认不存在」，诱导用户插入模板→保存覆盖已有契约；
  // 失败期间不渲染「尚无 verify.yaml」提示，改显失败提示与重试入口。
  const [yamlLoadError, setYamlLoadError] = useState(false);
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [autodraftLoading, setAutodraftLoading] = useState(false);
  // fix-verify-contract-signal-semantics D3：同步防重入锁——setAutodraftLoading 的
  // loading 渲染生效存在 React 调度间隙（实证 100ms 内双击穿透），useRef 写读同帧
  // 原子、无渲染依赖，在途期间重复触发直接 return 不发网络请求。
  const autodraftInFlight = useRef(false);
  // 过期响应守卫：每次发起加载自增序号，响应回来时序号已不是最新（期间切换了
  // 项目或发起了新加载）则丢弃——防止慢响应乱序把旧项目的契约内容写进当前
  // 项目草稿，进而被「保存 verify.yaml」以当前项目名写盘造成跨项目覆盖。
  const yamlLoadSeq = useRef(0);
  // 草稿归属守卫：记录草稿内容对应的（项目, 加载序号），保存前比对——
  // 首次加载未完成（草稿还是空串）或期间已切换项目（草稿仍是上一个项目的
  // 内容）时拒绝保存，防止以当前项目名把旧契约/空串写盘覆盖既有契约。
  const yamlDraftSourceRef = useRef<{ project: string; seq: number } | null>(null);
  // 草稿保护：镜像当前草稿值（加载回调是异步闭包，读不到最新 state）+
  // 最近一次服务器返回内容基线。静默回写（保存后重载）前比对——草稿既不
  // 等于基线也不等于服务器新内容，说明有未保存的用户修改，保留草稿并提示，
  // 防止用户输入被回写静默覆盖丢失。
  const yamlDraftRef = useRef('');
  const yamlLoadedContentRef = useRef('');

  // 页签/作用域切换丢弃确认（code-review item 8a3eb01dc2b9）：本面板自持
  // 简介/verify.yaml 两份独立草稿（非 antd Form），切页签/切作用域前由 index
  // 统一判脏弹确认。判脏采用探针实时比对两份草稿与各自基线（code-review
  // item 4815d4896312）：单一脏布尔会让「保存其一」连带清掉另一份草稿的未
  // 保存标记（简介保存走父级 handleSave 的统一复位、yaml 保存走本面板的
  // setDirty(false)），另一份草稿的丢弃确认随之失效；探针按各草稿自身落盘
  // 状态归零——简介保存成功后父级重载回填 config，yaml 保存成功后
  // loadVerifyYaml(true) 重打基线，任一草稿仍有未保存改动即脏。
  // 内联箭头的引用稳定性由 usePanelDirty 的 probeRef 每渲染镜像保证
  // （注册效果只跑一次，探针读到最新闭包），置于两份基线声明之后避免
  // 引用未初始化的 ref。
  usePanelDirty(
    () =>
      description !== (config.description || '') ||
      yamlDraftRef.current !== yamlLoadedContentRef.current,
  );

  // 草稿统一写入口：同步 ref 镜像（编辑 onChange 与「插入模板」共用）。
  // 置脏无需显式登记：探针按 yamlDraftRef 与基线实时比对（上方
  // usePanelDirty）；加载回填直接 setYamlDraft 并同步基线，同样不会误报脏。
  const applyYamlDraft = (value: string) => {
    yamlDraftRef.current = value;
    setYamlDraft(value);
  };

  const loadVerifyYaml = async (silent = false) => {
    const seq = ++yamlLoadSeq.current;
    if (!project) return;
    if (!silent) setYamlLoading(true);
    try {
      const d = await getVerifyYaml(project);
      if (seq !== yamlLoadSeq.current) return; // 过期响应：丢弃，不回写草稿
      setYamlLoadError(false); // 加载成功：清除失败标记
      if (
        silent &&
        yamlDraftRef.current !== d.content &&
        yamlDraftRef.current !== yamlLoadedContentRef.current
      ) {
        // 静默回写遇未保存草稿（既不等于刚保存/上次加载内容，也不等于服务
        // 器新内容）：保留用户编辑不覆盖，仅同步存在性/归属/基线并提示。
        // 非静默加载（「重新加载」按钮/切项目）是显式动作，维持直接覆盖。
        setYamlExists(d.exists);
        yamlLoadedContentRef.current = d.content;
        yamlDraftSourceRef.current = { project, seq };
        message.warning(
          '服务器上的 verify.yaml 已重新加载，但本地草稿有未保存修改，已保留您的编辑；如需丢弃修改请点击「重新加载」'
        );
        return;
      }
      setYamlDraft(d.content);
      yamlDraftRef.current = d.content;
      setYamlExists(d.exists);
      yamlLoadedContentRef.current = d.content;
      yamlDraftSourceRef.current = { project, seq };
    } catch (e) {
      if (seq !== yamlLoadSeq.current) return; // 过期请求的失败也不打扰当前项目
      setYamlLoadError(true); // 失败时不让 yamlExists 的旧值冒充「确认不存在」
      console.error('Failed to load verify.yaml:', e);
      message.error(`加载 verify.yaml 失败：${e instanceof Error ? e.message : e}`);
    } finally {
      // 非 silent 是 yamlLoading 的置位者，无条件清理自身锁——即使响应已过期
      // （保存触发的静默重载会自增 seq 令并发「重新加载」的响应过期），否则
      // 置位者的清理被跳过后 yamlLoading 永久悬挂为 true（编辑区整体禁用且
      // 无超时兜底）；提前清掉并发的另一把非 silent 加载锁也只是提前解禁
      // 编辑区，无害。silent 未置位该锁，仅当仍是最新加载时才顺带清理
      // （code-review item 5e9ba75a5074：原注释把两侧条件写反，此版与代码对齐）。
      if (!silent || seq === yamlLoadSeq.current) setYamlLoading(false);
    }
  };

  useEffect(() => {
    // 切项目：清草稿保护基线，草稿归属随加载切到新项目（回写按既有行为
    // 直接覆盖），防止上一项目残留基线把新项目内容误判为「覆盖未保存修改」
    yamlDraftRef.current = '';
    yamlLoadedContentRef.current = '';
    setYamlLoadError(false); // 清上一个项目残留的失败标记
    loadVerifyYaml();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  const handleYamlSave = async () => {
    if (!project) return;
    // 过期草稿守卫：加载未完成或草稿仍属于上一个项目（切项目的加载往返
    // 窗口内残留）时，以当前项目名写盘会覆盖既有契约——放弃保存并提示。
    const src = yamlDraftSourceRef.current;
    if (!src || src.project !== project || src.seq !== yamlLoadSeq.current) {
      message.warning('verify.yaml 内容尚未加载完成（或已切换项目），请重新加载后再保存');
      return;
    }
    setYamlSaving(true);
    try {
      await saveVerifyYaml(project, yamlDraft);
      message.success('verify.yaml 已保存');
      setYamlExists(true);
      // 已落盘草稿不再是「未保存改动」（code-review item 4815d4896312）：
      // 无需（也不能）手动清整面板脏标记——简介草稿的脏态须保留。先把基线
      // 同步为本次已保存内容（code-review item d9f2bd1097f0），静默重载仅用于
      // 对账服务端归一化差异：重载失败时基线不停留在保存前旧内容，已落盘
      // 草稿不会被探针误判为脏（切页签误弹丢弃确认）；归属随推进到当前加载
      // 序号，重载失败后也无需先「重新加载」即可再次保存。
      yamlLoadedContentRef.current = yamlDraft;
      await loadVerifyYaml(true);
      yamlDraftSourceRef.current = { project, seq: yamlLoadSeq.current };
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save verify.yaml:', e);
    } finally {
      setYamlSaving(false);
    }
  };

  const handleInsertTemplate = async () => {
    try {
      const d = await getVerifyYamlTemplate();
      // 走统一写入口：模板内容与已加载基线不同即视为未保存修改，
      // 在途静默回写不会把模板覆盖掉
      applyYamlDraft(d.template);
      message.info('已插入契约模板：按项目实际取消注释并修改，保存后下一轮验证生效');
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`模板加载失败：${errorMessage}`);
      console.error('Failed to load verify.yaml template:', e);
    }
  };

  const handleAutodraft = async (overwrite: boolean) => {
    if (!project) return;
    if (autodraftInFlight.current) return; // 竞态窗口内重复触发：同步锁拦截
    autodraftInFlight.current = true;
    setAutodraftLoading(true);
    try {
      const result = await autodraftVerifyYaml(project, overwrite);
      if (result.ok) {
        if (result.status === 'dispatched') {
          message.success(result.message);
        } else {
          message.info(result.message);
        }
      } else {
        message.error(result.message || '自动起草失败');
      }
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`自动起草失败：${errorMessage}`);
      console.error('Failed to autodraft verify.yaml:', e);
    } finally {
      setAutodraftLoading(false);
      autodraftInFlight.current = false;
    }
  };

  return (
    <div>
      <h3>项目：{project}</h3>
      <Text type="secondary">项目级的具体设置信息。</Text>
      <Card style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>项目简介</h3>
        <Text type="secondary">
          项目简介将展示在概览页项目卡片和项目列表页，帮助快速了解项目用途。
        </Text>
        <TextArea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="暂无简介"
          autoSize={{ minRows: 4, maxRows: 8 }}
          style={{ marginTop: 12, marginBottom: 16 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          {/* 比照「插入模板」口径（code-review item ebece58414b8）：简介草稿与已
              保存值不一致时，AI 生成会覆盖未保存的手工修改并直接落盘，先弹确认；
              草稿与已保存一致时行为不变。判脏口径与 usePanelDirty 探针一致 */}
          {description !== (config.description || '') ? (
            <Popconfirm
              title="AI 生成将覆盖未保存的简介修改"
              description="当前简介有未保存的修改，生成后将直接保存并覆盖，确定继续？"
              okText="覆盖"
              cancelText="取消"
              onConfirm={handleRegenerate}
            >
              <Button loading={loading}>AI 自动生成</Button>
            </Popconfirm>
          ) : (
            <Button onClick={handleRegenerate} loading={loading}>
              AI 自动生成
            </Button>
          )}
          <Button type="primary" onClick={handleSave} loading={saving} disabled={saving}>
            保存
          </Button>
        </div>
      </Card>

      {/* verify.yaml 为项目级文件：验证契约查看与编辑 */}
      {project ? (
        <div ref={verifySectionRef}>
        <Card style={{ marginTop: 16 }} data-testid="verify-yaml-section">
          <h3 style={{ marginTop: 0 }}>验证契约（verify.yaml）</h3>
          <Text type="secondary">
            项目 <code>.fenix/verify.yaml</code> 声明应用如何构建（prepare）、如何被服务
            （serve）、何时算就绪（ready）。保存时做 YAML 语法校验；生效于下一轮验证。
            本文件随仓库提交，保存后建议尽快 commit（daemon 派发 agent 前会 stash
            未提交修改）。
          </Text>
          {!yamlExists && !yamlLoading && !yamlLoadError && (
            <Alert
              style={{ marginTop: 8 }}
              type="info"
              showIcon
              message="尚无 verify.yaml（无契约时框架回退旧行为），可插入模板后按项目修改保存。"
              data-testid="verify-yaml-missing-alert"
            />
          )}
          {yamlLoadError && !yamlLoading && (
            <Alert
              style={{ marginTop: 8 }}
              type="warning"
              showIcon
              message="verify.yaml 加载失败：无法确认服务器上是否已有契约，重试成功前请勿插入模板保存，以免覆盖已有契约。"
              action={
                <Button size="small" type="link" onClick={() => loadVerifyYaml()}>
                  重试
                </Button>
              }
              data-testid="verify-yaml-load-error-alert"
            />
          )}
          <TextArea
            ref={yamlTextareaRef}
            data-testid="verify-yaml-textarea"
            value={yamlDraft}
            onChange={(e) => applyYamlDraft(e.target.value)}
            disabled={yamlLoading}
            placeholder={'# 全注释 = 无契约。可点击「插入模板」开始配置。'}
            autoSize={{ minRows: 12, maxRows: 28 }}
            style={{ marginTop: 12, fontFamily: 'monospace' }}
          />
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              {yamlDraft.trim() ? (
                <Popconfirm
                  title="当前编辑内容将被模板覆盖"
                  description="未保存的修改会丢失，确定继续？"
                  okText="覆盖"
                  cancelText="取消"
                  onConfirm={handleInsertTemplate}
                >
                  <Button data-testid="verify-yaml-template" disabled={yamlLoading}>
                    插入模板
                  </Button>
                </Popconfirm>
              ) : (
                <Button
                  onClick={handleInsertTemplate}
                  disabled={yamlLoading}
                  data-testid="verify-yaml-template"
                >
                  插入模板
                </Button>
              )}
              {/* AI 自动生成按钮 */}
              {!yamlExists && !yamlLoading ? (
                <Popconfirm
                  title="AI 起草验证契约"
                  description="将探索项目 → 生成契约 → 三段自证 → 提交仓库，约数分钟"
                  okText="确认起草"
                  cancelText="取消"
                  onConfirm={() => handleAutodraft(false)}
                >
                  <Button
                    style={{ marginLeft: 8 }}
                    loading={autodraftLoading}
                    data-testid="verify-yaml-autodraft"
                  >
                    AI 自动生成
                  </Button>
                </Popconfirm>
              ) : yamlExists ? (
                <Popconfirm
                  title="⚠️ 覆盖现有契约"
                  description="现有验证契约将被覆盖，未保存的编辑也会丢失。确定继续？"
                  okText="确认覆盖"
                  cancelText="取消"
                  onConfirm={() => handleAutodraft(true)}
                >
                  <Button
                    style={{ marginLeft: 8 }}
                    loading={autodraftLoading}
                    data-testid="verify-yaml-autodraft"
                  >
                    AI 自动生成
                  </Button>
                </Popconfirm>
              ) : null}
              <Button
                style={{ marginLeft: 8 }}
                onClick={() => loadVerifyYaml()}
                data-testid="verify-yaml-reload"
              >
                重新加载
              </Button>
            </div>
            <Button
              type="primary"
              loading={yamlSaving}
              disabled={yamlLoading || !project}
              onClick={handleYamlSave}
              data-testid="verify-yaml-save"
            >
              保存 verify.yaml
            </Button>
          </div>
        </Card>
        </div>
      ) : (
        <Card style={{ marginTop: 16 }}>
          <Text type="secondary">
            验证契约为项目级文件（<code>.fenix/verify.yaml</code>）。查看与编辑请切换到项目级作用域。
          </Text>
        </Card>
      )}
    </div>
  );
}
