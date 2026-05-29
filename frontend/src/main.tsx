import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  ExternalLink,
  Flag,
  Gauge,
  KeyRound,
  Lightbulb,
  ListChecks,
  Moon,
  Play,
  RefreshCw,
  RotateCcw,
  Shield,
  Square,
  Sun,
  Trash2,
  Trophy,
  X,
  Zap,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:1349";

type Challenge = {
  id: string;
  title: string;
  description: string;
  category: string;
  task_type: string;
  difficulty: string;
  dataset_id: string;
  tags: string[];
  hint: string | null;
  status: string;
  target_url: string | null;
  ports: number[];
  solved: boolean;
  hint_viewed: boolean;
  hint_penalty: number;
  submission_count: number;
  score: number;
  error_message: string | null;
};

type AuditEvent = {
  id: string;
  timestamp: string;
  level: string;
  event_type: string;
  message: string;
  challenge_id: string | null;
  data: Record<string, unknown>;
};

type Submission = {
  id: number;
  challenge_id: string;
  answer: string;
  correct: boolean;
  score_before: number;
  score_after: number;
  created_at: string;
};

type ThemeMode = "dark" | "light";

function App() {
  const [token, setToken] = useState(localStorage.getItem("droplet_token") ?? "droplet_dev_admin");
  const [theme, setTheme] = useState<ThemeMode>(() => (localStorage.getItem("droplet_theme") === "light" ? "light" : "dark"));
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState("");
  const [hintContent, setHintContent] = useState<string | null>(null);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [eventLimit, setEventLimit] = useState<number>(() => {
    const saved = localStorage.getItem("droplet_event_limit");
    return saved ? parseInt(saved, 10) : 200;
  });
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const selected = useMemo(() => challenges.find((c) => c.id === selectedId), [challenges, selectedId]);
  const groups = useMemo(() => groupChallenges(challenges), [challenges]);

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(readApiError(text));
    }
    return response.json();
  }

  async function refresh() {
    localStorage.setItem("droplet_token", token);
    const data = await api<Challenge[]>("/api/challenges");
    setChallenges(data);
    const nextSelected = !selectedId || !data.some((c) => c.id === selectedId) ? data[0]?.id ?? "" : selectedId;
    if (nextSelected !== selectedId) {
      setSelectedId(nextSelected);
    }
    if (nextSelected) {
      await refreshEvents(nextSelected);
    }
  }

  async function refreshEvents(challengeId = selectedId, limit = eventLimit) {
    if (!challengeId) {
      setEvents([]);
      return;
    }
    const data = await api<AuditEvent[]>(`/api/challenges/${challengeId}/events?limit=${limit}`);
    setEvents(data);
  }

  async function refreshSubmissions(challengeId = selectedId) {
    if (!challengeId) {
      setSubmissions([]);
      return;
    }
    const data = await api<Submission[]>(`/api/challenges/${challengeId}/submissions?limit=50`);
    setSubmissions(data);
  }

  async function clearEvents(challengeId = selectedId) {
    if (!challengeId) return;
    await api(`/api/challenges/${challengeId}/events/clear`, { method: "POST" });
    setEvents([]);
  }

  async function runAction(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
      await refreshEvents();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("droplet_theme", theme);
  }, [theme]);

  useEffect(() => {
    setHintContent(null);
    setSubmissionMessage(null);
    setAnswer("");
    refreshEvents().catch((err) => setError(err instanceof Error ? err.message : String(err)));
    refreshSubmissions().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [token]);

  const running = selected?.status === "running";
  const starting = selected?.status === "starting";
  const stopping = selected?.status === "stopping";
  const solved = selected?.status === "solved";

  return (
    <main className="appFrame">
      <header className="commandBar">
        <div className="brandLockup">
          <div className="brandMark">
            <Shield size={22} />
          </div>
          <div>
            <span className="eyebrow">Droplet</span>
            <h1>自动化渗透评测</h1>
          </div>
        </div>

        <div className="commandControls">
          <label className="tokenInput" title="API Token">
            <KeyRound size={16} />
            <input value={token} onChange={(e) => setToken(e.target.value)} />
          </label>
          <button className="iconButton ghost" onClick={() => setTheme((v) => (v === "dark" ? "light" : "dark"))} title={theme === "dark" ? "切换白天模式" : "切换黑夜模式"}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button className="iconButton ghost danger" onClick={() => setShowResetConfirm(true)} disabled={busy} title="重置全部题目">
            <RotateCcw size={18} />
          </button>
          <button className="iconButton solid" onClick={() => runAction(async () => undefined)} disabled={busy} title="刷新">
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      {error && <ErrorDialog message={error} onClose={() => setError("")} />}

      {showResetConfirm && (
        <ConfirmDialog
          title="重置全部题目"
          message="这会切换到新的评测会话，隐藏当前进度和提交历史视图。正在运行的题目环境不会被强行删除。"
          confirmLabel="确定重置"
          busy={busy}
          onConfirm={() => runAction(async () => { await api("/api/challenges/reset-all", { method: "POST" }); setShowResetConfirm(false); })}
          onCancel={() => setShowResetConfirm(false)}
        />
      )}

      <StatsBand challenges={challenges} />

      <section className="evaluationGrid">
        <ChallengeSidebar groups={groups} selectedId={selectedId} onSelect={setSelectedId} />

        <section className="taskStack">
          {selected ? (
            <>
              <section className="taskDetail surface">
                <div className="detailHeader">
                  <div>
                    <div className="taskIdLine">
                      <span>{selected.id.toUpperCase()}</span>
                      <StatusPill value={selected.status} />
                    </div>
                    <h2>{selected.title}</h2>
                  </div>
                  <div className="actionCluster">
                    <button className="solid" onClick={() => runAction(async () => { await api(`/api/challenges/${selected.id}/start`, { method: "POST" }); })} disabled={running || starting || stopping}>
                      {selected.status === "solved" || selected.status === "error" ? <RotateCcw size={17} /> : <Play size={17} />}
                      {starting ? "启动中" : stopping ? "停止中" : running ? "运行中" : selected.status === "solved" || selected.status === "error" ? "重置环境" : "启动环境"}
                    </button>
                    <button className="ghost danger" onClick={() => runAction(async () => { await api(`/api/challenges/${selected.id}/stop`, { method: "POST" }); })} disabled={!running && !starting && !stopping}>
                      <Square size={16} />
                      停止
                    </button>
                  </div>
                </div>

                <div className="metaGrid">
                  <MetaCell label="分类" value={selected.category} />
                  <MetaCell label="难度" value={selected.difficulty} />
                  <MetaCell label="题目类型" value={selected.task_type} />
                  <MetaCell label="得分" value={`${selected.score.toFixed(2)}`} />
                  <MetaCell label="提交次数" value={`${selected.submission_count}`} />
                  <MetaCell label="状态" value={statusLabel(selected.status)} />
                </div>

                {selected.target_url && (
                  <div className="targetBand">
                    <div>
                      <span>目标地址</span>
                      <strong>{selected.target_url}</strong>
                    </div>
                    <div className="targetActions">
                      <button className="iconButton ghost" onClick={() => navigator.clipboard?.writeText(selected.target_url!)} title="复制">
                        <Copy size={16} />
                      </button>
                      <a className="iconLink" href={selected.target_url} target="_blank" rel="noreferrer" title="打开目标">
                        <ExternalLink size={16} />
                      </a>
                    </div>
                  </div>
                )}

                {selected.error_message && (
                  <div className="notice error">
                    <CircleDot size={16} />
                    <span>{selected.error_message}</span>
                  </div>
                )}

                <div className="descriptionPanel">
                  <span>题目详情</span>
                  <p>{selected.description || "暂无描述。"}</p>
                </div>

                <div className="tagShelf">
                  {selected.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                  {selected.hint && (
                    <button className="hintChip" onClick={() => runAction(async () => { const r = await api<{ content: string }>(`/api/challenges/${selected.id}/hint`, { method: "POST" }); setHintContent(r.content); })} disabled={busy}>
                      <Lightbulb size={13} />
                      提示 {selected.hint_viewed ? "(已使用)" : "-0.1"}
                    </button>
                  )}
                </div>

                {hintContent && (
                  <div className="hintPanel">
                    <span>提示内容</span>
                    <p>{hintContent}</p>
                  </div>
                )}
              </section>

              <section className="runQueue surface">
                <div className="panelHeader">
                  <div>
                    <span>Flag 提交</span>
                    <strong>{selected.id.toUpperCase()}</strong>
                  </div>
                  <StatusPill value={selected.status} />
                </div>

                <div className="submissionDock">
                  <label>
                    <Flag size={16} />
                    <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="FLAG{...}" disabled={selected.status !== "running" && !solved} />
                  </label>
                  <button className="solid" onClick={() => runAction(async () => { const r = await api<{ accepted: boolean; judged: boolean; correct: boolean | null; message: string }>(`/api/challenges/${selected.id}/submit`, { method: "POST", body: JSON.stringify({ answer }) }); if (r.accepted) { setAnswer(""); setSubmissionMessage(r.judged ? (r.correct ? "提交正确" : "提交错误") : "提交已记录，当前题目未配置平台判题"); } })} disabled={busy || selected.status !== "running" || !answer.trim()}>
                    提交 Flag
                  </button>
                </div>

                {submissionMessage && (
                  <div className="notice ok">
                    <CheckCircle2 size={16} />
                    <span>{submissionMessage}</span>
                  </div>
                )}

                {selected.solved && (
                  <div className="notice ok">
                    <CheckCircle2 size={16} />
                    <span>已解出！得分 {selected.score.toFixed(2)}</span>
                  </div>
                )}

                {submissions.length > 0 && (
                  <div className="submissionHistory">
                    <div className="panelHeader">
                      <div>
                        <span>提交历史</span>
                        <strong>{submissions.length} 次</strong>
                      </div>
                    </div>
                    <div className="submissionList">
                      {submissions.map((sub) => (
                        <div key={sub.id} className={`submissionRow ${sub.correct ? "correct" : "incorrect"}`}>
                          <span className="submissionAnswer">{sub.answer}</span>
                          <span className="submissionResult">{sub.correct ? "正确" : "错误"}</span>
                          <span className="submissionScore">{sub.score_after.toFixed(2)}</span>
                          <span className="submissionTime">{formatTime(sub.created_at)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </>
          ) : (
            <div className="emptyBox">请选择题目</div>
          )}
        </section>

        <ActivityRail
          selected={selected}
          events={events}
          onRefresh={() => refreshEvents()}
          onClear={() => runAction(() => clearEvents())}
          eventLimit={eventLimit}
          onLimitChange={(limit) => {
            setEventLimit(limit);
            localStorage.setItem("droplet_event_limit", String(limit));
            refreshEvents(undefined, limit);
          }}
        />
      </section>
    </main>
  );
}


function ActivityRail({
  selected,
  events,
  onRefresh,
  onClear,
  eventLimit,
  onLimitChange,
}: {
  selected: Challenge | undefined;
  events: AuditEvent[];
  onRefresh: () => void;
  onClear: () => void;
  eventLimit: number;
  onLimitChange: (limit: number) => void;
}) {
  const errors = events.filter((event) => event.level === "error").length;
  const visible = [...events].reverse();

  return (
    <aside className="traceRail surface">
      <div className="traceHeader">
        <div>
          <span>LLM / Agent 活动链</span>
          <strong>{selected ? selected.id.toUpperCase() : "未选择题目"}</strong>
        </div>
        <div className="traceStats">
          <span>{events.length} 事件</span>
          <span>{errors} 错误</span>
          <select
            className="limitSelect"
            value={eventLimit}
            onChange={(e) => onLimitChange(parseInt(e.target.value, 10))}
            title="显示数量"
          >
            <option value={10}>近 10 条</option>
            <option value={50}>近 50 条</option>
            <option value={100}>近 100 条</option>
            <option value={200}>近 200 条</option>
            <option value={500}>近 500 条</option>
          </select>
          <button className="iconButton ghost" onClick={onRefresh} title="刷新活动链" disabled={!selected}>
            <RefreshCw size={16} />
          </button>
          <button className="iconButton ghost danger" onClick={onClear} title="清理当前活动链" disabled={!selected || events.length === 0}>
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <div className="traceLedger">
        {!selected && <div className="emptyBox">选择题目后显示活动链</div>}
        {selected && visible.length === 0 && <div className="emptyBox">暂无日志事件</div>}
        {visible.map((event) => (
          <article className={`traceEvent ${eventTone(event)}`} key={event.id}>
            <div className="traceEventHeader">
              <Activity size={14} />
              <strong>{eventLabel(event.event_type)}</strong>
              <time>{formatTime(event.timestamp)}</time>
            </div>
            <pre>{formatEvent(event)}</pre>
          </article>
        ))}
      </div>
    </aside>
  );
}

function StatsBand({ challenges }: { challenges: Challenge[] }) {
  const total = challenges.length;
  const solved = challenges.filter((c) => c.solved).length;
  const running = challenges.filter((c) => isRunning(c.status)).length;
  const items = [
    { label: "题目", value: String(total), icon: <ListChecks size={17} />, tone: "blue" },
    { label: "运行中", value: String(running), icon: <Zap size={17} />, tone: "red" },
    { label: "已解出", value: String(solved), icon: <CheckCircle2 size={17} />, tone: "green" },
    { label: "进度", value: `${total ? Math.round((solved / total) * 100) : 0}%`, icon: <Gauge size={17} />, tone: "white" },
  ];

  return (
    <section className="statsBand">
      {items.map((item) => (
        <div className={`statTile ${item.tone}`} key={item.label}>
          {item.icon}
          <div>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        </div>
      ))}
    </section>
  );
}

function ChallengeSidebar({
  groups,
  selectedId,
  onSelect,
}: {
  groups: { id: string; name: string; challenges: Challenge[] }[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  return (
    <aside className="benchmarkRail">
      <div className="railHeader">
        <span>题目列表</span>
        <strong>{groups.reduce((n, g) => n + g.challenges.length, 0)}</strong>
      </div>
      <div className="benchmarkList">
        {groups.map((group) => {
          const open = expanded[group.id] ?? true;
          return (
            <section className="benchmarkBlock" key={group.id}>
              <button className="benchmarkTop" onClick={() => setExpanded((v) => ({ ...v, [group.id]: !v[group.id] }))}>
                <div className="benchmarkName">
                  <span>Dataset</span>
                  <strong>{group.name}</strong>
                </div>
                <div className="benchmarkRight">
                  <span className="countBadge">{group.challenges.length} 题</span>
                  <em>{group.challenges.filter((c) => c.solved).length}/{group.challenges.length}</em>
                  {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </div>
              </button>
              {open && (
                <div className="taskIndex">
                  {group.challenges.map((c) => (
                    <button key={c.id} className={selectedId === c.id ? "taskLine active" : "taskLine"} onClick={() => onSelect(c.id)}>
                      <span className={`statusDot ${c.status}`} />
                      <div>
                        <strong>{c.id.toUpperCase()}</strong>
                        <span>{c.title}</span>
                      </div>
                      {c.solved && <Trophy size={13} className="solveIcon" />}
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="metaCell">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`statusPill ${value}`}>{statusLabel(value)}</span>;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    not_started: "未开始",
    starting: "启动中",
    running: "运行中",
    stopping: "停止中",
    solved: "已解出",
    error: "错误",
  };
  return labels[value] ?? value;
}

function isRunning(status: string) {
  return status === "running" || status === "starting" || status === "stopping";
}

function groupChallenges(challenges: Challenge[]) {
  const groups = new Map<string, { id: string; name: string; challenges: Challenge[] }>();
  for (const c of challenges) {
    const id = c.dataset_id || "unknown-dataset";
    const group = groups.get(id) ?? { id, name: formatDatasetName(id), challenges: [] };
    group.challenges.push(c);
    groups.set(id, group);
  }
  return [...groups.values()];
}

function formatDatasetName(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function ErrorDialog({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true" aria-labelledby="error-title">
      <div className="dialogCard surface errorDialog">
        <div className="dialogHeader">
          <div className="dialogIcon error">
            <AlertTriangle size={20} />
          </div>
          <div>
            <span>系统错误</span>
            <strong id="error-title">操作未完成</strong>
          </div>
          <button className="iconButton ghost" onClick={onClose} title="关闭">
            <X size={16} />
          </button>
        </div>
        <pre>{message}</pre>
        <button className="solid dialogPrimary" onClick={onClose}>知道了</button>
      </div>
    </div>
  );
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="dialogCard surface">
        <div className="dialogHeader">
          <div className="dialogIcon warn">
            <RotateCcw size={20} />
          </div>
          <div>
            <span>确认操作</span>
            <strong id="confirm-title">{title}</strong>
          </div>
        </div>
        <p>{message}</p>
        <div className="dialogActions">
          <button className="ghost" onClick={onCancel} disabled={busy}>取消</button>
          <button className="solid danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}


function eventTone(event: AuditEvent) {
  if (event.level === "error") return "error";
  if (event.level === "warning") return "warn";
  if (["challenge_started", "challenge_solved", "submission_recorded"].includes(event.event_type)) return "ok";
  return "";
}

function eventLabel(value: string) {
  const labels: Record<string, string> = {
    challenges_loaded: "加载题目",
    challenge_start_requested: "启动请求",
    challenge_started: "环境就绪",
    challenge_start_failed: "启动失败",
    challenge_stopped: "环境停止",
    challenge_stopped_externally: "外部停止",
    submission_recorded: "提交记录",
    challenge_solved: "题目解出",
    hint_viewed: "查看提示",
    agent_event: "Agent 事件",
  };
  return labels[value] ?? value;
}

function formatEvent(event: AuditEvent) {
  const data = Object.keys(event.data || {}).length ? `\n${JSON.stringify(event.data, null, 2)}` : "";
  return `${event.message}${data}`;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function readApiError(text: string) {
  try {
    const parsed = JSON.parse(text);
    return typeof parsed.detail === "string" ? parsed.detail : text;
  } catch {
    return text;
  }
}

createRoot(document.getElementById("root")!).render(<App />);
