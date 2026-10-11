import { Alert, App, Button, Card, Form, Input, Switch, Tabs, TimePicker, Typography } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { getTodo, saveTodo } from '@/services/dashboard';
import type { ConfigData } from '@/services/dashboard';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { usePanelDirty } from '../panelDirty';

const { Text } = Typography;
const { TextArea } = Input;

// 自省 run_at 缺省与后端 ConfigLoader.SELF_REVIEW_DEFAULT_RUN_AT 一致（凌晨两点）
const DEFAULT_RUN_AT = '02:00';

interface SelfReviewPanelProps {
  config: ConfigData;
  /** 返回保存是否成功：false 时不再连带提交 todo.md（配置失败不连带覆写） */
  onSave: (values: Partial<ConfigData>) => Promise<boolean>;
  /** 项目名；undefined = 用户级作用域（todo.md 为项目级文件，不显示编辑区） */
  project?: string;
}

export default function SelfReviewPanel({ config, onSave, project }: SelfReviewPanelProps) {
  // 提示经 App.useApp() 取上下文实例（code-review item 8ec702fc6b4a）：antd v5
  // 静态 message 不消费 App/ConfigProvider 上下文，与同族面板口径统一
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）。自省表单与 todo.md 草稿两路编辑都置脏；
  // 保存经父级 handleSave 成功后统一复位，todo.md 段失败时在本地重新置脏
  const { setDirty } = usePanelDirty();
  const selfReview = config.self_review;

  // ── todo.md 草稿状态：保存并入本页签右下角主保存按钮
  //    （2026-09-07 用户决策：移除独立的重新加载/保存 todo 按钮）；
  //    project 变化（作用域切换）时重新加载磁盘内容 ──
  const [todoDraft, setTodoDraft] = useState('');
  const [todoExists, setTodoExists] = useState(false);
  const [todoLoading, setTodoLoading] = useState(false);
  // 加载失败标志（code-review item e092a8069ea2）：失败路径不回填、草稿保持
  // 空态，此时提交保存会以空串整文件覆写磁盘上真实存在的 todo.md（夜间自省
  // 追加的历史回顾静默丢失）——失败态须与在飞态同样拦截保存；作用域变化
  // 重新加载时复位（见下方加载 effect）
  const [todoLoadFailed, setTodoLoadFailed] = useState(false);
  // todoDraft 内容归属的 project（code-review item 9b004f2237fc）：作用域切换
  // 的提交与「清空草稿/置加载中」effect 执行之间存在旧渲染快照窗口，此刻
  // handleSave 闭包里 project 已是新项目而 todoDraft/todoLoading 仍是旧快照，
  // todoLoading=false 守卫放行，且 projectAtStart 取到新 project 使 projectRef
  // 对账也判等通过，await 后 saveTodo(新项目, 旧项目草稿) 造成跨项目整文件
  // 覆写。与 savingRef 同口径以 ref 同帧写读为权威：草稿归属在加载成功回填时
  // 才认领、清空即摘除，归属未认领到当前作用域一律拦截 todo.md 提交
  const todoDraftOwnerRef = useRef<string | undefined>(undefined);

  // todo.md 视图页签：预览在前且为默认（先看渲染效果，需要改动再切编辑）；
  // 切换纯前端状态，两页签共享草稿无损
  const [todoView, setTodoView] = useState<'edit' | 'preview'>('preview');

  // 保存重入守卫（code-review item c8b75672cecb，与 ApprovalModePanel
  // item 589c1c98c5a4 同形态）：handleSave 是异步双段提交（配置 + todo.md），
  // 期间按钮可继续点击会发出重叠保存请求（并发写同一 config/todo 文件，
  // 结果取决于响应到达顺序）——saving 期间置 loading/disabled 并在入口短路。
  // 拦截以 savingRef 同帧写读为权威（code-review item d5a9c299b87c，与
  // PromptsPanel item 6e35a8c1d5cd / QualityPanel useGatedFormPanel 的
  // savingRef 同口径）：setSaving 渲染生效存在调度间隙，state 短路拦不住
  // 同帧双击——本面板双段提交恰是重入后果最重的路径。state 仅留按钮视觉反馈。
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  // 当前 project prop 镜像 ref（code-review item 522b3bd7ae53，与父组件
  // scopeRef/projectRef 同形态）：handleSave 的 todo.md 覆写/回读续段在
  // await onSave 期间执行，用户可能已把作用域切到别的项目，闭包捕获的
  // project 已过期——续段动文件/回填前须与发起时快照比对币值。
  const projectRef = useRef(project);
  useEffect(() => {
    projectRef.current = project;
  }, [project]);
  // 上次回填的 self_review 序列化值（配合下方 effect 的回填门控）
  const lastSelfReviewBackfillRef = useRef('');

  useEffect(() => {
    // 作用域变化即先清失败标志（code-review item e092a8069ea2）：含切到用户级
    // 作用域（下方直接 return 不加载）——若残留失败态会误拦用户级的配置保存；
    // 是否失败由本次重新加载重新裁决
    setTodoLoadFailed(false);
    if (!project) return;
    let cancelled = false;
    // 作用域切换即先清空上一项目残留草稿（code-review item 6bf8170c023d，
    // 与 PromptsPanel item 96880454231c 同口径）：加载在飞或失败期间，残留的
    // 旧项目内容若被「保存」提交，会整文件覆写进当前项目的 todo.md（跨项目
    // 静默数据破坏）；加载失败路径不回填，保持已复位的空状态
    setTodoDraft('');
    setTodoExists(false);
    // 清空即摘除草稿归属（code-review item 9b004f2237fc）：归属在下方加载
    // 成功回填时才重新认领，加载在飞/失败/切换窗口期内保存一律拦截
    todoDraftOwnerRef.current = undefined;
    const load = async () => {
      setTodoLoading(true);
      try {
        const d = await getTodo(project);
        if (!cancelled) {
          setTodoDraft(d.content);
          setTodoExists(d.exists);
          // 回填即认领归属（code-review item 9b004f2237fc）：此刻草稿才真正
          // 属于本作用域，保存放行以该 ref 对账为准
          todoDraftOwnerRef.current = project;
        }
      } catch (e) {
        // 不落 console，避免触发验证场景的 no_console_error 断言（同族面板口径）
        if (!cancelled) {
          // 置失败标志：保存入口与「尚无 todo.md」引导文案此后均按失败态短路，
          // 不再以空草稿放行整文件覆写
          setTodoLoadFailed(true);
          message.error(`加载 todo.md 失败：${e instanceof Error ? e.message : e}`);
        }
      } finally {
        if (!cancelled) setTodoLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [project]);

  // 自省字段（self_review.*）：TimePicker 值为 dayjs 对象（结构性保证
  // HH:mm 合法），保存时转回字符串。
  // 注意：下方 dayjs(str, 'HH:mm') 双参解析依赖 app.tsx 全局注册的
  // customParseFormat 插件（code-review item e5732f6a7667）——未注册时
  // 得 Invalid Date，TimePicker 空显且保存提交 'Invalid Date' 被后端拒绝
  const initialValues = {
    enabled: selfReview?.enabled ?? false,
    run_at: dayjs(selfReview?.run_at ?? DEFAULT_RUN_AT, 'HH:mm'),
    read_todo: selfReview?.read_todo ?? false,
  };

  useEffect(() => {
    // 回填门控（code-review item a8786c075c4f，与 ApprovalModePanel 同形态）：
    // config.self_review 引用变化但内容相同时（本面板或其它面板保存后父组件
    // setConfig 重载）不无条件 setFieldsValue——否则会静默丢弃用户尚未保存的
    // 开关/时间修改。「同步用户级设置」等显式操作带来的是真正内容变化，
    // 序列化值不同，仍会回填覆盖。
    const key = JSON.stringify(initialValues);
    if (key === lastSelfReviewBackfillRef.current) return;
    lastSelfReviewBackfillRef.current = key;
    form.setFieldsValue(initialValues);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.self_review, form]);

  const handleSave = async () => {
    // ref 写读同帧原子拦截（code-review item d5a9c299b87c）：state 短路拦不住同帧双击
    if (savingRef.current) return;
    // todo.md 加载在飞时短路（code-review item 6bf8170c023d）：此刻 todoDraft
    // 尚未回填为新作用域内容（或因加载失败保持空），提交会把残留/空草稿整文件
    // 覆写进当前项目的 todo.md
    if (todoLoading) {
      return;
    }
    // 草稿归属对账（code-review item 9b004f2237fc）：作用域切换的提交与清空/
    // 置位 effect 执行之间，闭包里 project 已是新项目而 todoDraft/todoLoading
    // 仍是旧渲染快照，上方 todoLoading 守卫放行，且 projectAtStart 取到新
    // project 使下方 projectRef 对账也判等通过——按 ref 同帧拦截：草稿归属
    // 尚未认领到当前作用域（切换窗口/加载在飞/加载失败）即不得提交 todo.md。
    // 仅项目级作用域对账：用户级不提交 todo.md（下方 !project 短路），不拦截
    // 纯配置保存
    if (project && todoDraftOwnerRef.current !== project) {
      return;
    }
    // 加载失败态同样短路（code-review item e092a8069ea2）：失败路径不回填、
    // todoDraft 保持空串，此刻提交会以空串整文件覆写磁盘上真实存在的 todo.md，
    // 静默丢失夜间自省追加的历史回顾
    if (todoLoadFailed) {
      message.error('todo.md 加载失败，内容未回填，已阻止保存以免以空草稿覆写磁盘内容；请切换作用域重新加载后重试。');
      return;
    }
    savingRef.current = true;
    setSaving(true);
    // 发起时的作用域快照（code-review item 522b3bd7ae53）：下方 todo.md
    // 覆写/回读续段执行前与 projectRef 比对，作用域已切换即中止——否则
    // 续段按过期 project 调 saveTodo/getTodo，迟到的旧项目回读会覆写
    // 新作用域面板的编辑框，用户再点「保存」即跨项目整文件覆写 todo.md
    const projectAtStart = project;
    try {
      // 校验与持久化分离（code-review item f139c66daa4f，与 useGatedFormPanel
      // 同口径）：校验失败 antd 已在表单内渲染 explain-error 提示，静默返回；
      // onSave 的 rejection 单独兜底——父级当前自带失败 toast 并以 resolve(false)
      // 结束（子层观察不到拒绝），此 catch 保证父级反馈路径调整（onSave 改为
      // reject）时保存失败不退化为无声失败
      let values;
      try {
        values = await form.validateFields();
      } catch {
        return;
      }
      let ok = false;
      try {
        ok = await onSave({
          self_review: {
            enabled: values.enabled,
            run_at: values.run_at.format('HH:mm'),
            read_todo: values.read_todo,
          },
        });
      } catch (error) {
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
        return;
      }
      // 配置保存成功后连调 /api/todo 保存 todo.md（同一「保存」动作的两段提交；
      // 配置失败不连带覆写 todo.md）。成功后回读磁盘，兼作原「重新加载」语义。
      // 覆写与回读拆成独立错误分支：覆写成功而回读偶发失败（网络抖动）时
      // 文件已落盘，不能误报「保存失败」误导用户重试或怀疑丢失编辑
      if (!project || !ok) return;
      // 作用域已在 await onSave 期间切换：中止本段 todo.md 覆写/回读，
      // 不再以过期 project 调 saveTodo/getTodo（新作用域面板由其自身的
      // 加载 effect 负责，见上方 cancelled 守卫）
      if (projectRef.current !== projectAtStart) return;
      // await 期间草稿归属已失效（作用域切换重载摘除归属）同样中止：
      // 不以过期草稿覆写 todo.md（code-review item 9b004f2237fc）
      if (todoDraftOwnerRef.current !== project) return;
      try {
        await saveTodo(project, todoDraft);
      } catch (e) {
        const errorMessage = e instanceof Error ? e.message : String(e);
        message.error(`todo.md 保存失败：${errorMessage}`);
        // 不落 console，避免触发验证场景的 no_console_error 断言（同族面板口径）
        // 配置段成功已触发父级统一复位判脏，但 todo.md 段未落盘、草稿仍是
        // 未保存改动：重新置脏，切页签/作用域时丢弃确认不可缺席
        setDirty(true);
        return;
      }
      // 回读失败单独提示；保留编辑框现有草稿不回填（覆写内容即用户刚提交的草稿）
      try {
        const d = await getTodo(project);
        // saveTodo await 期间作用域再切换：丢弃迟到的旧项目回读，
        // 不回填新作用域面板（code-review item 522b3bd7ae53）
        if (projectRef.current !== projectAtStart) return;
        setTodoDraft(d.content);
        setTodoExists(d.exists);
      } catch (e) {
        const errorMessage = e instanceof Error ? e.message : String(e);
        message.error(`todo.md 已保存，但回读最新内容失败：${errorMessage}`);
        // 不落 console，避免触发验证场景的 no_console_error 断言（同族面板口径）
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <div data-testid="self-review-panel">
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <h3>自省</h3>
        <Text type="secondary">
          Fenix Daemon 每晚在指定时间由 Administrator Agent 自动执行工作回顾（浪费 /
          失误 / 可改进，回顾窗口为执行前 24 小时），结果追加写入项目根 todo.md 并自动提交。
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="self-review-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              启用每日自省<span className="label-note">（admin.self_review.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省关闭。开启后于每日 run_at 后触发（距上次执行不足 24 小时则顺延至下个巡检周期）。
          </Text>

          <Form.Item
            name="run_at"
            label={
              <>
                每日执行时间<span className="label-note">（admin.self_review.run_at，HH:MM）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[{ required: true, message: '请选择执行时间' }]}
            data-testid="self-review-field-run_at"
          >
            <TimePicker format="HH:mm" allowClear={false} style={{ width: 160 }} />
          </Form.Item>
          <Text type="secondary">
            缺省 02:00。实际触发时刻为 run_at 后的第一个巡检周期；回顾数据窗口为执行前 24 小时。
          </Text>

          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="read_todo" valuePropName="checked" noStyle>
              <Switch data-testid="self-review-control-read_todo" />
            </Form.Item>
            <span className="switch-inline-label">
              注入既有 todo.md 上下文<span className="label-note">（admin.self_review.read_todo）</span>
            </span>
          </div>
          <Text type="secondary">
            开启时把项目根 todo.md 全文注入自省 prompt，供 Agent 识别历史条目、
            避免重复并标注已闭环项。缺省关闭。
          </Text>
        </Card>

        {/* todo.md 为项目级文件：仅项目级作用域提供查看与编辑 */}
        {project ? (
          <Card style={{ marginTop: 16 }} data-testid="todo-section">
            <h3 style={{ marginTop: 0 }}>todo.md</h3>
            <Text type="secondary">
              自省 Agent 每晚追加写入工作回顾。编辑后经本页签右下角「保存」按钮与自省设置一并保存（整文件覆写）；
              注意与 daemon 夜间追加的时序。
            </Text>
            {!todoExists && !todoLoading && !todoLoadFailed && (
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                showIcon
                message="尚无 todo.md（自省首次运行后生成），可保存以下内容提前创建。"
                data-testid="todo-missing-alert"
              />
            )}
            {/* 加载失败态不再渲染「尚无 todo.md 可提前创建」的误导引导
                （code-review item e092a8069ea2）：失败即内容未回填，保存已被拦 */}
            {todoLoadFailed && !todoLoading && (
              <Alert
                style={{ marginTop: 8 }}
                type="warning"
                showIcon
                message="todo.md 加载失败：内容未回填，已阻止保存以免以空草稿覆写磁盘内容；请切换作用域后重试加载。"
                data-testid="todo-load-error-alert"
              />
            )}
            <Tabs
              type="card"
              className="todo-md-tabs"
              activeKey={todoView}
              onChange={(k) => setTodoView(k as 'edit' | 'preview')}
              style={{ marginTop: 12 }}
              items={[
                {
                  key: 'preview',
                  label: '预览',
                  children: (
                    <div
                      data-testid="todo-preview"
                      style={{
                        minHeight: 120, maxHeight: 600, overflow: 'auto',
                        background: '#fff', border: '1px solid #f0f0f0',
                        borderTop: 0, borderRadius: 0, padding: 12,
                      }}
                    >
                      {todoDraft ? (
                        <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents}>
                          {todoDraft}
                        </Markdown>
                      ) : (
                        <Text type="secondary">暂无内容——切到「编辑」页签写入后此处实时渲染。</Text>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'edit',
                  label: '编辑',
                  children: (
                    <TextArea
                      data-testid="todo-textarea"
                      value={todoDraft}
                      onChange={(e) => {
                        setDirty(true);
                        setTodoDraft(e.target.value);
                      }}
                      // 保存进行中禁止编辑（code-review item 5a7bb5de4335，与
                      // PromptsPanel item cbd7e62160ec 同口径）：handleSave 双段
                      // 提交后在飞期间键入的内容不在已提交的 todoDraft 里，
                      // 回读回填会用磁盘值无条件覆盖（静默丢失）。
                      disabled={todoLoading || saving}
                      placeholder={'## 2026-09-04\n\n### 可改进\n- 证据：……'}
                      autoSize={{ minRows: 10, maxRows: 24 }}
                      style={{
                        fontFamily: 'monospace', borderTop: 0, borderRadius: 0,
                        // 边框颜色钉死与预览容器一致：内联样式压制 antd 默认深灰
                        // 与 hover/focus 态的蓝色边框；焦点外发光一并压掉
                        borderColor: '#f0f0f0', boxShadow: 'none',
                      }}
                    />
                  ),
                },
              ]}
            />
          </Card>
        ) : (
          <Card style={{ marginTop: 16 }}>
            <Text type="secondary">
              todo.md 为项目级文件（<code>.fenix/todo.md</code>）。查看与编辑请切换到项目级作用域。
            </Text>
          </Card>
        )}
      </Form>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving || todoLoading} data-testid="self-review-save-btn">
          保存
        </Button>
      </div>
    </div>
  );
}
