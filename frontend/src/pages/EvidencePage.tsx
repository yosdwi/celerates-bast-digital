import { useEffect, useMemo, useState } from "react";
import { getTaskEvidence } from "../api/talentops";
import type { CommandCenterResponse, EmployeeRole, TalentOpsSession, TaskEvidenceItem } from "../api/types";
import { CloseIcon, SearchIcon } from "../components/Icons";
import WorkspaceFrame from "../components/WorkspaceFrame";

type TeamFilter = "all" | EmployeeRole;

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

const dateFormatter = new Intl.DateTimeFormat("id-ID", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const timeFormatter = new Intl.DateTimeFormat("id-ID", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function EvidencePage({ session, data, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [items, setItems] = useState<TaskEvidenceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<TaskEvidenceItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setItems([]);
    setSelected(null);
    void getTaskEvidence(data.period, { limit: 60, offset: 0 })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Unable to load task evidence.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [data.period.month, data.period.year]);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filtered = useMemo(
    () => items.filter((item) => {
      if (teamFilter !== "all" && item.role !== teamFilter) return false;
      if (!normalizedSearch) return true;
      return `${item.full_name} ${item.nrp} ${item.task_title} ${item.caption}`
        .toLocaleLowerCase()
        .includes(normalizedSearch);
    }),
    [items, normalizedSearch, teamFilter],
  );

  async function loadMore() {
    if (loadingMore || items.length >= total) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await getTaskEvidence(data.period, { limit: 60, offset: items.length });
      setItems((current) => [...current, ...page.items]);
      setTotal(page.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load more evidence.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <WorkspaceFrame
      session={session}
      active="evidence"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => onNavigate("/admin/talentops/")}
    >
      <div className="content evidence-page">
        <div className="page-heading evidence-heading">
          <div>
            <h1>Task Evidence</h1>
            <p>{data.period.label} · fast-look preview of evidence already uploaded by talent</p>
          </div>
          <div className="evidence-count"><strong>{total}</strong><span>uploads</span></div>
        </div>

        <div className="evidence-boundary-note">
          <strong>Read-only review.</strong> A valid upload already completes the task evidence requirement. There is no PMO approve, reject, verified, duplicate-check, or AI-validation state here.
        </div>

        <div className="evidence-toolbar">
          <div className="panel-search evidence-search">
            <SearchIcon />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search talent, NRP, task, or caption"
              aria-label="Search task evidence"
            />
          </div>
          <select
            value={teamFilter}
            onChange={(event) => setTeamFilter(event.target.value as TeamFilter)}
            aria-label="Filter evidence by team"
          >
            <option value="all">All teams</option>
            <option value="Developer">Developer</option>
            <option value="IoT Operations">IoT Operations</option>
          </select>
        </div>

        {error ? <div className="refresh-error" role="status">{error}</div> : null}
        {loading ? <div className="evidence-loading">Loading task evidence…</div> : null}
        {!loading && filtered.length === 0 ? (
          <div className="empty-state evidence-empty">No task evidence matches this view.</div>
        ) : null}

        <section className="evidence-grid" aria-label="Task evidence uploads">
          {filtered.map((item) => (
            <button
              className="evidence-card"
              type="button"
              key={item.id}
              onClick={() => setSelected(item)}
            >
              <div className="evidence-thumb">
                <img src={item.image_url} alt={`Evidence for ${item.task_title}`} loading="lazy" />
              </div>
              <div className="evidence-card-body">
                <div className="evidence-card-person">
                  <strong>{item.full_name}</strong>
                  <span>{item.nrp} · {item.role}</span>
                </div>
                <div className="evidence-task-title">{item.task_title}</div>
                <div className="evidence-card-meta">
                  <span>{dateFormatter.format(new Date(`${item.work_date}T00:00:00`))}</span>
                  <span>{item.task_source}</span>
                  <span>{formatBytes(item.byte_size)}</span>
                </div>
                {item.caption ? <p>{item.caption}</p> : null}
              </div>
            </button>
          ))}
        </section>

        {!loading && items.length < total ? (
          <div className="evidence-load-more">
            <button className="secondary-button" type="button" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? "Loading…" : `Load more (${items.length}/${total})`}
            </button>
          </div>
        ) : null}
      </div>

      <div className={`evidence-preview-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`evidence-preview ${selected ? "open" : ""}`} aria-hidden={!selected}>
        {selected ? (
          <>
            <div className="evidence-preview-head">
              <div>
                <span>{selected.nrp} · {selected.role}</span>
                <h2>{selected.full_name}</h2>
              </div>
              <button className="icon-button" type="button" aria-label="Close evidence preview" onClick={() => setSelected(null)}>
                <CloseIcon />
              </button>
            </div>
            <div className="evidence-preview-image">
              <img src={selected.image_url} alt={`Evidence for ${selected.task_title}`} />
            </div>
            <div className="evidence-preview-body">
              <span className="evidence-preview-label">Task</span>
              <h3>{selected.task_title}</h3>
              <dl>
                <div><dt>Work date</dt><dd>{dateFormatter.format(new Date(`${selected.work_date}T00:00:00`))}</dd></div>
                <div><dt>Uploaded</dt><dd>{timeFormatter.format(new Date(selected.uploaded_at))}</dd></div>
                <div><dt>Source</dt><dd>{selected.task_source}</dd></div>
                <div><dt>File</dt><dd>{selected.content_type} · {formatBytes(selected.byte_size)}</dd></div>
              </dl>
              {selected.caption ? <><span className="evidence-preview-label">Caption</span><p>{selected.caption}</p></> : null}
            </div>
            <div className="evidence-preview-actions">
              <button className="primary-button" type="button" onClick={() => onOpenTalent(selected.nrp)}>
                Open Talent 360
              </button>
            </div>
          </>
        ) : null}
      </aside>
    </WorkspaceFrame>
  );
}
