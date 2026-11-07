import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BadgeCheck,
  Banknote,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  Filter,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, api } from "./api";
import type {
  DashboardSummary,
  ExportResult,
  PayGateException,
  PayrollInput,
  Scorecard,
  ValidationRun,
} from "./types";

type Section = "overview" | "exceptions" | "payroll" | "approvals" | "scorecard";
type Action = { kind: "approve"; id: string } | { kind: "waive"; id: string };

const navItems: { id: Section; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "exceptions", label: "Exceptions", icon: ShieldAlert },
  { id: "payroll", label: "Payroll inputs", icon: Banknote },
  { id: "approvals", label: "Approvals & export", icon: FileCheck2 },
  { id: "scorecard", label: "Evaluation", icon: Activity },
];

const chartColors = { tp: "#2b8066", fp: "#e4a241", fn: "#bd5b62" };
const pageSize = 12;

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(parsed);
}

function StatusPill({ value }: { value: string }) {
  const tone =
    value === "APPROVED" || value === "RELEASED" || value === "RESOLVED"
      ? "green"
      : value === "BLOCKED" || value === "OPEN" || value.toUpperCase() === "CRITICAL"
        ? "red"
        : value === "WAIVED" || value === "ACKNOWLEDGED"
          ? "amber"
          : "slate";
  return <span className={`status-pill status-${tone}`}>{value.replaceAll("_", " ")}</span>;
}

function Panel({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><FileCheck2 size={21} /></div>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

function Pagination({
  total,
  offset,
  onChange,
}: {
  total: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const page = Math.floor(offset / pageSize) + 1;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pagination">
      <span>{total ? `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}` : "0 results"}</span>
      <div className="pagination-actions">
        <button className="icon-button" disabled={page <= 1} onClick={() => onChange(offset - pageSize)} aria-label="Previous page">
          <ChevronLeft size={17} />
        </button>
        <span>Page {page} of {pages}</span>
        <button className="icon-button" disabled={page >= pages} onClick={() => onChange(offset + pageSize)} aria-label="Next page">
          <ChevronRight size={17} />
        </button>
      </div>
    </div>
  );
}

function App() {
  const [section, setSection] = useState<Section>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [scorecardError, setScorecardError] = useState("");
  const [exceptions, setExceptions] = useState<PayGateException[]>([]);
  const [exceptionTotal, setExceptionTotal] = useState(0);
  const [exceptionOffset, setExceptionOffset] = useState(0);
  const [exceptionStatus, setExceptionStatus] = useState("");
  const [exceptionQuery, setExceptionQuery] = useState("");
  const [inputs, setInputs] = useState<PayrollInput[]>([]);
  const [inputTotal, setInputTotal] = useState(0);
  const [inputOffset, setInputOffset] = useState(0);
  const [inputStatus, setInputStatus] = useState("");
  const [inputQuery, setInputQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState(false);
  const [validationLoading, setValidationLoading] = useState(false);
  const validationInFlight = useRef(false);
  const [error, setError] = useState("");
  const [validationRun, setValidationRun] = useState<ValidationRun | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [approver, setApprover] = useState("");
  const [comment, setComment] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [exportGroup, setExportGroup] = useState("");
  const [exportPeriod, setExportPeriod] = useState("");
  const [exportActor, setExportActor] = useState("");
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState<ApiError | null>(null);
  const [lastExport, setLastExport] = useState<ExportResult | null>(null);

  const loadSummary = useCallback(async () => {
    const result = await api.dashboard();
    setSummary(result);
    if (!exportGroup && result.export_options.length) {
      setExportGroup(result.export_options[0].pay_group_id);
      setExportPeriod(result.export_options[0].period_id);
    }
    return result;
  }, [exportGroup]);

  const loadScorecard = useCallback(async () => {
    try {
      setScorecard(await api.scorecard());
      setScorecardError("");
    } catch (reason) {
      setScorecard(null);
      setScorecardError(reason instanceof Error ? reason.message : "Scorecard could not be loaded.");
    }
  }, []);

  const loadExceptions = useCallback(async () => {
    const result = await api.exceptions(pageSize, exceptionOffset, exceptionStatus, exceptionQuery);
    setExceptions(result.items);
    setExceptionTotal(result.total);
  }, [exceptionOffset, exceptionQuery, exceptionStatus]);

  const loadInputs = useCallback(async () => {
    const result = await api.inputs(pageSize, inputOffset, inputStatus, inputQuery);
    setInputs(result.items);
    setInputTotal(result.total);
  }, [inputOffset, inputQuery, inputStatus]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const results = await Promise.allSettled([
      loadSummary(),
      loadScorecard(),
      loadExceptions(),
      loadInputs(),
    ]);
    const summaryResult = results[0];
    if (summaryResult.status === "rejected") {
      setError(summaryResult.reason instanceof Error ? summaryResult.reason.message : "Dashboard data could not be loaded.");
    }
    setLoading(false);
  }, [loadExceptions, loadInputs, loadScorecard, loadSummary]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const updateLists = useCallback(async () => {
    setListLoading(true);
    const results = await Promise.allSettled([loadExceptions(), loadInputs()]);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") {
      setNotice(failed.reason instanceof Error ? failed.reason.message : "A list could not be refreshed.");
    }
    setListLoading(false);
  }, [loadExceptions, loadInputs]);

  useEffect(() => {
    if (!loading) void updateLists();
  }, [exceptionOffset, exceptionQuery, exceptionStatus, inputOffset, inputQuery, inputStatus]); // reload only on list controls

  const chooseSection = (next: Section) => {
    setSection(next);
    setMobileNavOpen(false);
  };

  const runValidation = async () => {
    if (validationInFlight.current) return;
    validationInFlight.current = true;
    setValidationLoading(true);
    setNotice("");
    try {
      const result = await api.runValidation();
      setValidationRun(result);
      setNotice(`Validation ${result.run_id} completed with ${result.finding_count} finding${result.finding_count === 1 ? "" : "s"}.`);
      await refresh();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Validation could not be run.");
    } finally {
      validationInFlight.current = false;
      setValidationLoading(false);
    }
  };

  const openAction = (next: Action) => {
    setAction(next);
    setApprover("");
    setComment("");
    setNotice("");
  };

  const submitAction = async (event: FormEvent) => {
    event.preventDefault();
    if (!action || !approver.trim() || !comment.trim()) return;
    setActionLoading(true);
    try {
      if (action.kind === "approve") await api.approve(action.id, approver, comment);
      else await api.waive(action.id, approver, comment);
      setAction(null);
      setNotice(action.kind === "approve" ? "Payroll input approved." : "Exception waiver recorded.");
      await refresh();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "The operation could not be completed.");
    } finally {
      setActionLoading(false);
    }
  };

  const submitExport = async (event: FormEvent) => {
    event.preventDefault();
    setExportError(null);
    setLastExport(null);
    setExportLoading(true);
    try {
      const result = await api.export(exportGroup, exportPeriod, exportActor);
      if (result.status === "RELEASED") {
        setLastExport(result);
        setNotice(`Export ${result.export_id} was released by the backend.`);
        await refresh();
      } else {
        setNotice(`Export ${result.export_id} was created with status ${result.status}; release is not confirmed.`);
      }
    } catch (reason) {
      setExportError(reason instanceof ApiError ? reason : new ApiError("Export request failed.", 0));
    } finally {
      setExportLoading(false);
    }
  };

  const pageTitle = navItems.find((item) => item.id === section)?.label ?? "Overview";
  const chartData = useMemo(
    () => Object.entries(scorecard?.by_rule_id ?? {}).map(([rule, metrics]) => ({ rule, ...metrics })),
    [scorecard],
  );
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><ShieldCheck size={21} strokeWidth={2.2} /></div>
          <div><strong>paygate</strong><span>PAYROLL OPERATIONS</span></div>
          <button className="mobile-close icon-button" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <div className="workspace-switcher">
          <div className="workspace-avatar">PG</div>
          <div><strong>PayGate workspace</strong><span>Configured database</span></div>
          <ChevronDown size={15} />
        </div>
        <p className="nav-caption">WORKSPACE</p>
        <nav className="main-nav" aria-label="Main navigation">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${section === id ? "nav-item-active" : ""}`} onClick={() => chooseSection(id)}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
              {id === "exceptions" && summary && summary.validation_finding_count > 0 && (
                <span className="nav-count">{summary.validation_finding_count}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="secure-note"><ShieldCheck size={17} /><div><strong>Controlled access</strong><span>Operations are audit logged</span></div></div>
          <div className="user-profile">
            <div className="user-avatar">OP</div>
            <div><strong>Current operator</strong><span>Identity not authenticated</span></div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      {mobileNavOpen && <button className="mobile-scrim" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation overlay" />}

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button className="mobile-menu icon-button" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
            <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{pageTitle}</strong></div>
          </div>
          <div className="topbar-actions">
            <span className="today-label"><span className="live-dot" /> Live data</span>
            <button className="button button-quiet" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} /> Refresh</button>
          </div>
        </header>

        <div className="page-content">
          <div className="page-intro">
            <div>
              <p className="eyebrow">PAYROLL CONTROL CENTER</p>
              <h1>{pageTitle}</h1>
              <p className="intro-copy">A clear view of payroll readiness, validation and controlled exports.</p>
            </div>
            {section !== "scorecard" && (
              <button className="button button-primary" onClick={() => void runValidation()} disabled={validationLoading}>
                {validationLoading ? <LoaderCircle size={16} className="spin" /> : <Activity size={16} />}
                {validationLoading ? "Validating…" : "Run validation"}
              </button>
            )}
          </div>

          {error && <div className="alert alert-error"><CircleAlert size={18} /><div><strong>Dashboard unavailable</strong><p>{error}</p></div><button onClick={() => void refresh()} className="alert-action">Retry</button></div>}
          {notice && <div className={`alert ${notice.toLowerCase().includes("could not") || notice.toLowerCase().includes("failed") ? "alert-error" : "alert-success"}`} role="status"><Check size={17} /><p>{notice}</p><button className="alert-dismiss" onClick={() => setNotice("")} aria-label="Dismiss message"><X size={15} /></button></div>}

          {loading && !summary ? (
            <div className="loading-screen"><LoaderCircle className="spin" size={27} /><span>Loading payroll workspace…</span></div>
          ) : (
            <>
              {section === "overview" && (
                <Overview
                  summary={summary}
                  scorecard={scorecard}
                  scorecardError={scorecardError}
                  validationRun={validationRun}
                  loading={loading}
                  onRun={runValidation}
                  onGo={chooseSection}
                />
              )}
              {section === "exceptions" && (
                <ExceptionsView
                  items={exceptions}
                  total={exceptionTotal}
                  offset={exceptionOffset}
                  status={exceptionStatus}
                  query={exceptionQuery}
                  loading={listLoading}
                  onStatus={(value) => { setExceptionOffset(0); setExceptionStatus(value); }}
                  onQuery={(value) => { setExceptionOffset(0); setExceptionQuery(value); }}
                  onPage={setExceptionOffset}
                  onWaive={(id) => openAction({ kind: "waive", id })}
                />
              )}
              {section === "payroll" && (
                <PayrollView
                  items={inputs}
                  total={inputTotal}
                  offset={inputOffset}
                  status={inputStatus}
                  query={inputQuery}
                  loading={listLoading}
                  onStatus={(value) => { setInputOffset(0); setInputStatus(value); }}
                  onQuery={(value) => { setInputOffset(0); setInputQuery(value); }}
                  onPage={setInputOffset}
                />
              )}
              {section === "approvals" && (
                <ApprovalsView
                  items={inputs}
                  total={inputTotal}
                  offset={inputOffset}
                  loading={listLoading}
                  summary={summary}
                  exportGroup={exportGroup}
                  exportPeriod={exportPeriod}
                  exportActor={exportActor}
                  exportLoading={exportLoading}
                  exportError={exportError}
                  lastExport={lastExport}
                  onGroup={(value) => {
                    setExportGroup(value);
                    setExportPeriod(summary?.export_options.find((item) => item.pay_group_id === value)?.period_id ?? "");
                    setExportError(null);
                    setLastExport(null);
                  }}
                  onPeriod={(value) => { setExportPeriod(value); setExportError(null); }}
                  onActor={setExportActor}
                  onExport={submitExport}
                  onApprove={(id) => openAction({ kind: "approve", id })}
                  onPage={setInputOffset}
                />
              )}
              {section === "scorecard" && (
                <ScorecardView scorecard={scorecard} error={scorecardError} chartData={chartData} />
              )}
            </>
          )}
          <footer className="page-footer"><span>PayGate payroll validation</span><span>Operational data is served by your configured API.</span></footer>
        </div>
      </main>

      {action && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAction(null); }}>
          <form className="action-modal" onSubmit={(event) => void submitAction(event)}>
            <div className="modal-top">
              <div className="modal-icon">{action.kind === "approve" ? <BadgeCheck size={22} /> : <ShieldCheck size={22} />}</div>
              <button type="button" className="icon-button" onClick={() => setAction(null)} aria-label="Close dialog"><X size={18} /></button>
            </div>
            <p className="eyebrow">AUDIT-LOGGED ACTION</p>
            <h2>{action.kind === "approve" ? "Approve payroll input" : "Waive blocking exception"}</h2>
            <p className="modal-copy">{action.kind === "approve" ? action.id : `Exception ${action.id}`} · The action and comment will be recorded by the backend.</p>
            <label className="field-label">Approver identity<input value={approver} onChange={(event) => setApprover(event.target.value)} placeholder="e.g. HR-OPERATOR-01" required /></label>
            <label className="field-label">Comment<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add a review comment…" rows={3} required /></label>
            <div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setAction(null)}>Cancel</button><button className="button button-primary" disabled={actionLoading || !approver.trim() || !comment.trim()}>{actionLoading ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{actionLoading ? "Submitting…" : action.kind === "approve" ? "Confirm approval" : "Record waiver"}</button></div>
          </form>
        </div>
      )}
    </div>
  );
}

function Overview({
  summary,
  scorecard,
  scorecardError,
  validationRun,
  loading,
  onRun,
  onGo,
}: {
  summary: DashboardSummary | null;
  scorecard: Scorecard | null;
  scorecardError: string;
  validationRun: ValidationRun | null;
  loading: boolean;
  onRun: () => void;
  onGo: (section: Section) => void;
}) {
  if (!summary) return <EmptyState title="No dashboard data available" />;
  const cards = [
    { label: "Total employees", value: summary.employee_count, icon: Users, tone: "mint", note: "In the configured dataset" },
    { label: "Payroll inputs", value: summary.payroll_input_count, icon: Banknote, tone: "blue", note: "Across available periods" },
    { label: "Validation findings", value: summary.validation_finding_count, icon: ShieldAlert, tone: "gold", note: "Latest validation run" },
    { label: "Blocked inputs", value: summary.blocked_input_count, icon: CircleAlert, tone: "rose", note: "Require review" },
    { label: "Successful exports", value: summary.successful_export_count, icon: ArrowDownToLine, tone: "violet", note: "Released by backend" },
  ];
  return (
    <div className="section-stack">
      <div className="metric-grid">
        {cards.map(({ label, value, icon: Icon, tone, note }) => (
          <div className="metric-card" key={label}>
            <div className={`metric-icon metric-${tone}`}><Icon size={19} /></div>
            <span className="metric-label">{label}</span>
            <strong className="metric-value">{loading ? "—" : formatNumber(value)}</strong>
            <span className="metric-note">{note}</span>
          </div>
        ))}
      </div>

      <div className="overview-grid">
        <Panel title="Validation scorecard" description="Detection against the available ground-truth dataset." action={<button className="text-link" onClick={() => onGo("scorecard")}>Full scorecard <ArrowRight size={14} /></button>}>
          {scorecard ? (
            <>
              <div className="scorecard-stats">
                <MiniMetric label="True positives" value={scorecard.overall.tp} color="green" />
                <MiniMetric label="False positives" value={scorecard.overall.fp} color="amber" />
                <MiniMetric label="False negatives" value={scorecard.overall.fn} color="red" />
              </div>
              <div className="metric-bars">
                <PercentBar label="Precision" value={scorecard.overall.precision} color="green" />
                <PercentBar label="Recall" value={scorecard.overall.recall} color="blue" />
                <PercentBar label="F1 score" value={scorecard.overall.f1} color="violet" />
              </div>
              <p className="small-note">Metrics reflect the available labels in dataset <strong>{String(scorecard.dataset.identifier ?? "configured dataset")}</strong>; unlabelled findings are not independently adjudicated.</p>
            </>
          ) : <EmptyState title={scorecardError || "Scorecard is not available"}><button className="text-link" onClick={() => onGo("scorecard")}>View evaluation status <ArrowRight size={14} /></button></EmptyState>}
        </Panel>
        <Panel title="Latest validation run" description="Most recent persisted rule execution." action={<button className="icon-button" onClick={onRun} aria-label="Run validation"><RefreshCw size={16} /></button>}>
          {summary.latest_validation_run ? (
            <div className="run-overview">
              <div className="run-id-line"><span className="run-check"><Check size={15} /></span><div><strong>{summary.latest_validation_run.run_id}</strong><span>{formatDate(summary.latest_validation_run.started_at)}</span></div><StatusPill value="COMPLETED" /></div>
              <div className="run-detail-grid"><div><span>Findings</span><strong>{summary.latest_validation_run.finding_count}</strong></div><div><span>Blocked inputs</span><strong className={summary.latest_validation_run.blocked_input_count ? "text-red" : ""}>{summary.latest_validation_run.blocked_input_count}</strong></div><div><span>Validated inputs</span><strong>{summary.latest_validation_run.validated_input_count}</strong></div></div>
            </div>
          ) : <EmptyState title="No validation run yet">Run validation to inspect current payroll data against the active rules.</EmptyState>}
          {validationRun && <div className="inline-result"><Check size={15} /> Just completed {validationRun.run_id} · {validationRun.finding_count} findings</div>}
          <button className="button button-outline run-button" onClick={onRun} disabled={loading}><Activity size={16} /> Run validation now</button>
        </Panel>
      </div>

      {validationRun && (
        <Panel title="Manual validation result" description={`Persisted run ${validationRun.run_id} · ${formatDate(validationRun.started_at)}`}>
          <div className="validation-result-summary">
            <div><span>Findings</span><strong>{validationRun.finding_count}</strong></div>
            <div><span>Blocked inputs</span><strong className={validationRun.blocked_inputs.length ? "text-red" : ""}>{validationRun.blocked_inputs.length}</strong></div>
            <div><span>Validated inputs</span><strong>{validationRun.validated_inputs.length}</strong></div>
          </div>
          <div className="validation-result-details">
            <details>
              <summary>Blocked payroll input IDs ({validationRun.blocked_inputs.length}) <ChevronDown size={14} /></summary>
              {validationRun.blocked_inputs.length ? <ul>{validationRun.blocked_inputs.map((id) => <li className="mono" key={id}>{id}</li>)}</ul> : <p className="muted-text">No blocked inputs in this run.</p>}
            </details>
            <details>
              <summary>Findings ({validationRun.finding_count}) <ChevronDown size={14} /></summary>
              {validationRun.findings.length ? <div className="run-finding-list">{validationRun.findings.map((finding) => <div className="run-finding" key={finding.exception_id}><div><strong>{finding.rule_id}</strong><span className="mono">{finding.exception_id}</span><StatusPill value={finding.severity} /></div><p>{finding.message ?? "No validation event message was recorded."}</p><details className="evidence-details"><summary>View evidence <ChevronDown size={14} /></summary><pre>{JSON.stringify(finding.evidence, null, 2)}</pre></details></div>)}</div> : <p className="muted-text">This run produced no findings.</p>}
            </details>
          </div>
        </Panel>
      )}

      <Panel title="Recent exports" description="Latest export records returned by the API." action={<button className="text-link" onClick={() => onGo("approvals")}>Create export <ArrowRight size={14} /></button>}>
        {summary.recent_exports.length ? (
          <div className="table-scroll"><table><thead><tr><th>Export ID</th><th>Pay group</th><th>Period</th><th>Net total (minor units)</th><th>Created</th><th>Status</th></tr></thead><tbody>
            {summary.recent_exports.map((item) => <tr key={item.export_id}><td className="mono">{item.export_id}</td><td>{item.pay_group_id}</td><td>{item.period_id}</td><td>{formatNumber(item.total_net_minor)}</td><td>{formatDate(item.created_at)}</td><td><StatusPill value={item.status} /></td></tr>)}
          </tbody></table></div>
        ) : <EmptyState title="No exports yet">A released export will appear here after the export gate succeeds.</EmptyState>}
      </Panel>
    </div>
  );
}

function MiniMetric({ label, value, color }: { label: string; value: number; color: string }) {
  return <div className="mini-metric"><span className={`mini-dot dot-${color}`} /><span>{label}</span><strong>{formatNumber(value)}</strong></div>;
}

function PercentBar({ label, value, color }: { label: string; value: number; color: string }) {
  return <div className="percent-row"><div><span>{label}</span><strong>{(value * 100).toFixed(1)}%</strong></div><div className="progress-track"><div className={`progress-fill fill-${color}`} style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} /></div></div>;
}

function ExceptionsView({
  items, total, offset, status, query, loading, onStatus, onQuery, onPage, onWaive,
}: {
  items: PayGateException[]; total: number; offset: number; status: string; query: string; loading: boolean;
  onStatus: (value: string) => void; onQuery: (value: string) => void; onPage: (offset: number) => void; onWaive: (id: string) => void;
}) {
  return (
    <div className="section-stack">
      <div className="callout callout-neutral"><ShieldAlert size={18} /><p>Finding evidence and messages below are returned by the validation API. No additional recommendations are supplied by the backend.</p></div>
      <Panel title="Validation exceptions" description={`${formatNumber(total)} records · Evidence is available per finding`}>
        <div className="table-toolbar">
          <label className="search-field"><Search size={16} /><input maxLength={100} value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search rule, employee, period…" /></label>
          <label className="select-field"><Filter size={15} /><select value={status} onChange={(event) => onStatus(event.target.value)}><option value="">All statuses</option><option>OPEN</option><option>ACKNOWLEDGED</option><option>RESOLVED</option><option>WAIVED</option><option>SUPERSEDED</option></select></label>
        </div>
        {loading ? <ListLoading /> : items.length ? (
          <div className="exception-list">
            {items.map((item) => (
              <article className="exception-card" key={item.exception_id}>
                <div className="exception-top">
                  <div className="exception-heading"><span className={`severity-mark severity-${item.severity.toLowerCase()}`} /><div><span className="mono exception-id">{item.exception_id}</span><h3>{item.rule_name}</h3></div></div>
                  <div className="exception-badges"><StatusPill value={item.severity} /><StatusPill value={item.status} /></div>
                </div>
                <div className="exception-meta"><span><strong>{item.rule_id}</strong> · {item.entity_type.replaceAll("_", " ")}</span><span>Employee <strong>{item.employee_id ?? "—"}</strong></span><span>Period <strong>{item.period_id ?? "—"}</strong></span><span>{item.blocking ? "Blocking rule" : "Non-blocking rule"}</span></div>
                {item.message && <p className="exception-message">{item.message}</p>}
                <details className="evidence-details"><summary>View evidence <ChevronDown size={14} /></summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details>
                <div className="exception-bottom"><span className="muted-text">Run {item.run_id} · {item.entity_id}</span>{item.blocking && ["OPEN", "ACKNOWLEDGED"].includes(item.status) && <button className="button button-outline button-small" onClick={() => onWaive(item.exception_id)}><ShieldCheck size={14} /> Waive with HR comment</button>}</div>
              </article>
            ))}
          </div>
        ) : <EmptyState title="No exceptions match this view">Run validation or adjust your filters to see findings.</EmptyState>}
        <Pagination total={total} offset={offset} onChange={onPage} />
      </Panel>
    </div>
  );
}

function PayrollView({
  items, total, offset, status, query, loading, onStatus, onQuery, onPage,
}: {
  items: PayrollInput[]; total: number; offset: number; status: string; query: string; loading: boolean;
  onStatus: (value: string) => void; onQuery: (value: string) => void; onPage: (offset: number) => void;
}) {
  return (
    <Panel title="Payroll inputs" description={`${formatNumber(total)} inputs · Amounts are shown in database minor units`}>
      <div className="table-toolbar">
        <label className="search-field"><Search size={16} /><input maxLength={100} value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search employee, ID, or period…" /></label>
        <label className="select-field"><Filter size={15} /><select value={status} onChange={(event) => onStatus(event.target.value)}><option value="">All statuses</option>{["AGGREGATED", "VALIDATED", "BLOCKED", "APPROVED", "EXPORTED"].map((item) => <option key={item}>{item}</option>)}</select></label>
      </div>
      {loading ? <ListLoading /> : items.length ? (
        <div className="table-scroll"><table><thead><tr><th>Payroll input</th><th>Employee</th><th>Pay group / period</th><th>Regular hours</th><th>OT hours</th><th>Net (minor units)</th><th>Status</th></tr></thead><tbody>
          {items.map((item) => <tr key={item.payroll_input_id}><td className="mono">{item.payroll_input_id}</td><td><strong>{item.employee_name}</strong><span className="table-sub">{item.employee_id}</span></td><td>{item.pay_group_id}<span className="table-sub">{item.period_id}</span></td><td>{formatNumber(item.regular_hours)}</td><td>{formatNumber(item.ot_hours)}</td><td>{formatNumber(item.net_minor)}</td><td><StatusPill value={item.status} /></td></tr>)}
        </tbody></table></div>
      ) : <EmptyState title="No payroll inputs found">Try a different search or status filter.</EmptyState>}
      <Pagination total={total} offset={offset} onChange={onPage} />
    </Panel>
  );
}

function ApprovalsView({
  items, total, offset, loading, summary, exportGroup, exportPeriod, exportActor, exportLoading, exportError, lastExport,
  onGroup, onPeriod, onActor, onExport, onApprove, onPage,
}: {
  items: PayrollInput[]; total: number; offset: number; loading: boolean; summary: DashboardSummary | null;
  exportGroup: string; exportPeriod: string; exportActor: string; exportLoading: boolean; exportError: ApiError | null; lastExport: ExportResult | null;
  onGroup: (value: string) => void; onPeriod: (value: string) => void; onActor: (value: string) => void; onExport: (event: FormEvent) => void; onApprove: (id: string) => void; onPage: (offset: number) => void;
}) {
  const groups = Array.from(new Map((summary?.export_options ?? []).map((option) => [option.pay_group_id, option.pay_group_name])).entries());
  const periods = summary?.export_options.filter((option) => option.pay_group_id === exportGroup) ?? [];
  return (
    <div className="section-stack">
      <Panel title="Approval queue" description="Approval actions are available for validated or blocked inputs. The API enforces blockers and lifecycle state.">
        {loading ? <ListLoading /> : items.length ? (
          <div className="table-scroll"><table><thead><tr><th>Input / employee</th><th>Period</th><th>Net (minor units)</th><th>Status</th><th>Action</th></tr></thead><tbody>
            {items.map((item) => <tr key={item.payroll_input_id}><td><strong>{item.employee_name}</strong><span className="table-sub mono">{item.payroll_input_id}</span></td><td>{item.period_id}</td><td>{formatNumber(item.net_minor)}</td><td><StatusPill value={item.status} /></td><td>{["VALIDATED", "BLOCKED"].includes(item.status) ? <button className="button button-outline button-small" onClick={() => onApprove(item.payroll_input_id)}><BadgeCheck size={14} /> Review & approve</button> : <span className="muted-text">No action available</span>}</td></tr>)}
          </tbody></table></div>
        ) : <EmptyState title="No inputs in this page">Inputs can be searched and paged in Payroll inputs.</EmptyState>}
        <Pagination total={total} offset={offset} onChange={onPage} />
      </Panel>

      <div className="export-layout">
        <Panel title="Request payroll export" description="The export gate checks input approvals, unresolved blocking exceptions and source time-entry approval before writing any export records.">
          <form className="export-form" onSubmit={onExport}>
            <label className="field-label">Pay group<select required value={exportGroup} onChange={(event) => onGroup(event.target.value)}><option value="">Select pay group</option>{groups.map(([id, name]) => <option value={id} key={id}>{name} · {id}</option>)}</select></label>
            <label className="field-label">Pay period<select required value={exportPeriod} onChange={(event) => onPeriod(event.target.value)}><option value="">Select period</option>{periods.map((option) => <option key={`${option.pay_group_id}-${option.period_id}`} value={option.period_id}>{option.period_id}</option>)}</select></label>
            <label className="field-label">Requested by<input required value={exportActor} onChange={(event) => onActor(event.target.value)} placeholder="Payroll operator identity" /></label>
            <button className="button button-primary" disabled={exportLoading || !exportGroup || !exportPeriod || !exportActor.trim()}>{exportLoading ? <LoaderCircle size={16} className="spin" /> : <ArrowDownToLine size={16} />}{exportLoading ? "Checking eligibility…" : "Request export"}</button>
          </form>
          {exportError && <div className="alert alert-error export-rejection"><CircleAlert size={18} /><div><strong>{exportError.status === 409 ? "Export not eligible" : "Export request failed"}</strong><p>{exportError.message}</p>{exportError.reasons.length > 0 && <ul>{exportError.reasons.map((reason, index) => <li key={`${reason.code}-${index}`}><span className="mono">{reason.code}</span> — {reason.message}</li>)}</ul>}</div></div>}
          {lastExport?.status === "RELEASED" && <div className="export-success"><div className="success-icon"><Check size={19} /></div><div><span>Backend confirmed release</span><strong>{lastExport.export_id}</strong><p>{lastExport.line_count} lines · {formatNumber(lastExport.total_net_minor)} minor units · {lastExport.period_id}</p></div><StatusPill value={lastExport.status} /></div>}
        </Panel>
        <Panel title="Export controls" description="Exports are confirmed only after the backend returns RELEASED.">
          <div className="gate-list"><GateItem title="Approved payroll inputs" detail="Every input in the selected scope must be approved." /><GateItem title="Blocking exceptions" detail="No unresolved blocking exception may remain." /><GateItem title="Source time entries" detail="Contributing time entries must be approved." /><GateItem title="Atomic release" detail="The API creates the export and lines in one transaction." /></div>
          <div className="callout callout-neutral export-note"><ShieldCheck size={17} /><p>No client-side status is treated as export success. Conflicts are displayed from the API response.</p></div>
        </Panel>
      </div>
    </div>
  );
}

function GateItem({ title, detail }: { title: string; detail: string }) {
  return <div className="gate-item"><span><Check size={14} /></span><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

function ScorecardView({ scorecard, error, chartData }: { scorecard: Scorecard | null; error: string; chartData: { rule: string; tp: number; fp: number; fn: number }[] }) {
  if (!scorecard) return <Panel title="Validation scorecard" description="Evaluation compares persisted findings with the configured dataset labels."><EmptyState title={error || "No scorecard available"}>Run validation to create a persisted run. Ground-truth evaluation is only available when the configured API dataset provides labels.</EmptyState></Panel>;
  const metrics = [
    ["True positives", scorecard.overall.tp, "green"],
    ["False positives", scorecard.overall.fp, "amber"],
    ["False negatives", scorecard.overall.fn, "red"],
    ["Planted issues", scorecard.overall.total_planted_issues, "blue"],
  ];
  return (
    <div className="section-stack">
      <div className="callout callout-info"><Activity size={18} /><p>Evaluation metrics compare validation findings against the <strong>available ground-truth dataset</strong>. They do not establish that every unlabelled finding is an actual error.</p></div>
      <div className="metric-grid metric-grid-four">{metrics.map(([label, value, tone]) => <div className="metric-card compact-metric" key={label as string}><span className={`mini-dot dot-${tone}`} /><span className="metric-label">{label}</span><strong className="metric-value">{formatNumber(value as number)}</strong></div>)}</div>
      <Panel title="Detection quality" description={`Run ${scorecard.validation_run_id} · ${String(scorecard.dataset.identifier ?? "Configured dataset")}`}>
        <div className="quality-grid"><QualityMetric label="Precision" value={scorecard.overall.precision} /><QualityMetric label="Recall" value={scorecard.overall.recall} /><QualityMetric label="F1 score" value={scorecard.overall.f1} /></div>
      </Panel>
      <Panel title="Rule-level findings" description="Counts follow strict rule-specific matching.">
        {chartData.length ? <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 12, right: 12, left: -18, bottom: 4 }} barGap={5}><CartesianGrid stroke="#edf0f4" vertical={false} /><XAxis dataKey="rule" tickLine={false} axisLine={false} tick={{ fill: "#738093", fontSize: 12 }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#8a95a4", fontSize: 11 }} /><Tooltip cursor={{ fill: "#f6f8fa" }} contentStyle={{ border: "1px solid #e8edf2", borderRadius: 12, boxShadow: "0 8px 24px rgba(24,38,53,.08)" }} /><Bar dataKey="tp" name="True positives" fill={chartColors.tp} radius={[4, 4, 0, 0]} /><Bar dataKey="fp" name="False positives" fill={chartColors.fp} radius={[4, 4, 0, 0]} /><Bar dataKey="fn" name="False negatives" fill={chartColors.fn} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div> : <EmptyState title="No rule metrics available" />}
      </Panel>
      <Panel title="Rule metrics" description="Strict TP / FP / FN results by validation rule.">
        <div className="table-scroll"><table><thead><tr><th>Rule</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{chartData.map((item) => <tr key={item.rule}><td><strong>{item.rule}</strong></td><td>{item.tp}</td><td>{item.fp}</td><td>{item.fn}</td><td>{(scorecard.by_rule_id[item.rule].precision * 100).toFixed(1)}%</td><td>{(scorecard.by_rule_id[item.rule].recall * 100).toFixed(1)}%</td><td>{(scorecard.by_rule_id[item.rule].f1 * 100).toFixed(1)}%</td></tr>)}</tbody></table></div>
      </Panel>
    </div>
  );
}

function QualityMetric({ label, value }: { label: string; value: number }) {
  const percent = Math.max(0, Math.min(100, value * 100));
  const color = percent >= 80 ? chartColors.tp : percent >= 50 ? chartColors.fp : chartColors.fn;
  return <div className="quality-card"><div className="quality-ring" style={{ background: `conic-gradient(${color} ${percent}%, #edf0f4 ${percent}% 100%)` }}><div>{percent.toFixed(1)}%</div></div><strong>{label}</strong></div>;
}

function ListLoading() {
  return <div className="list-loading"><LoaderCircle size={19} className="spin" /> Loading records…</div>;
}

export default App;
