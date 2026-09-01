import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { getTalentMobileLinks } from "../api/talent-mobile-links";
import type { TalentMobileLinkItem, TalentMobileLinksResponse } from "../api/talent-mobile-links";
import { askCommandCenter } from "../api/talentops";
import type { CommandCenterResponse, EmployeeRole, TalentOpsSession } from "../api/types";
import { ChevronIcon, CloseIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import { StatusBadge, statusLabel } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

type TeamFilter = "all" | EmployeeRole;
type StateFilter = "all" | "attention" | "complete";
type DirectoryTab = "directory" | "links";

function percentage(value: number, total: number): string {
  return total === 0 ? "0%" : `${Math.round((value / total) * 100)}%`;
}

function accessLabel(link: TalentMobileLinkItem | undefined): string {
  if (!link) return "Belum dimuat";
  if (link.status === "not_configured") return "Public URL belum dikonfigurasi";
  return link.whatsapp_bound ? "Siap dibagikan" : "Siap dibagikan · WA belum terhubung";
}

function validityLabel(ttlSeconds: number | undefined): string {
  if (!ttlSeconds) return "menunggu generate";
  const days = Math.max(1, Math.round(ttlSeconds / (24 * 60 * 60)));
  return `${days} hari`;
}

export default function TalentsPage({ session, data, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [team, setTeam] = useState<TeamFilter>("all");
  const [state, setState] = useState<StateFilter>("all");
  const [tab, setTab] = useState<DirectoryTab>("directory");
  const [links, setLinks] = useState<TalentMobileLinksResponse | null>(null);
  const [linksLoading, setLinksLoading] = useState(false);
  const [linksError, setLinksError] = useState(false);
  const [copiedEmployee, setCopiedEmployee] = useState<string | null>(null);
  const [copiedListCount, setCopiedListCount] = useState<number | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Which talents need PMO attention this period, and why?");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiUnavailable, setAiUnavailable] = useState(false);

  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return data.readiness.filter((talent) => {
      const searchOk = !needle || `${talent.name} ${talent.nrp} ${talent.role}`.toLocaleLowerCase().includes(needle);
      const teamOk = team === "all" || talent.role === team;
      const stateOk = state === "all"
        || (state === "attention" ? talent.overall_state !== "complete" : talent.overall_state === "complete");
      return searchOk && teamOk && stateOk;
    });
  }, [data.readiness, search, state, team]);

  const linksByEmployee = useMemo(
    () => new Map((links?.items ?? []).map((item) => [item.employee_id, item])),
    [links],
  );

  const developerCount = data.readiness.filter((item) => item.role === "Developer").length;
  const iotCount = data.readiness.filter((item) => item.role === "IoT Operations").length;

  async function loadLinks() {
    if (linksLoading) return;
    setLinksLoading(true);
    setLinksError(false);
    setCopiedEmployee(null);
    setCopiedListCount(null);
    try {
      setLinks(await getTalentMobileLinks(data.period));
    } catch {
      setLinks(null);
      setLinksError(true);
    } finally {
      setLinksLoading(false);
    }
  }

  useEffect(() => {
    setLinks(null);
    setCopiedEmployee(null);
    setCopiedListCount(null);
    if (tab === "links") void loadLinks();
    // Period changes must invalidate previously issued signed links.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.period.year, data.period.month, tab]);

  async function copyTalentLink(item: TalentMobileLinkItem | undefined) {
    if (!item?.url) return;
    try {
      await navigator.clipboard.writeText(item.url);
      setCopiedEmployee(item.employee_id);
      window.setTimeout(() => setCopiedEmployee((current) => current === item.employee_id ? null : current), 1800);
    } catch {
      setCopiedEmployee(null);
    }
  }

  async function copyVisibleTalentLinks() {
    if (linksLoading || visible.length === 0) return;
    setLinksError(false);
    setCopiedListCount(null);

    let currentLinks = links;
    if (!currentLinks) {
      setLinksLoading(true);
      try {
        currentLinks = await getTalentMobileLinks(data.period);
        setLinks(currentLinks);
      } catch {
        setLinksError(true);
        return;
      } finally {
        setLinksLoading(false);
      }
    }

    const currentLinksByEmployee = new Map(currentLinks.items.map((item) => [item.employee_id, item]));
    const rows = visible.flatMap((talent) => {
      const url = currentLinksByEmployee.get(talent.employee_id)?.url;
      return url ? [`${talent.name} — ${url}`] : [];
    });
    if (rows.length === 0) return;

    const filters = [
      team === "all" ? "Semua tim" : team,
      state === "all" ? "Semua readiness" : state === "attention" ? "Need attention" : "Ready",
    ];
    if (search.trim()) filters.push(`Search: ${search.trim()}`);

    const text = [
      `Talent Mobile — ${data.period.label}`,
      `Filter: ${filters.join(" · ")}`,
      "",
      ...rows,
    ].join("\n");

    try {
      await navigator.clipboard.writeText(text);
      setCopiedListCount(rows.length);
      window.setTimeout(() => setCopiedListCount(null), 2200);
    } catch {
      setCopiedListCount(null);
    }
  }

  async function submitAi(event?: FormEvent) {
    event?.preventDefault();
    const question = aiQuestion.trim();
    if (!question || aiLoading) return;
    setAiLoading(true);
    setAiUnavailable(false);
    try {
      const response = await askCommandCenter(session.csrf_token, question, data.period);
      setAiAnswer(response.answer);
      setAiUnavailable(response.status === "unavailable");
    } catch {
      setAiAnswer(null);
      setAiUnavailable(true);
    } finally {
      setAiLoading(false);
    }
  }

  return (
    <WorkspaceFrame
      session={session}
      active="talents"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => setAiOpen(true)}
    >
      <div className="content slice2-content">
        <div className="page-heading">
          <div><h1>Talents</h1><p>{data.period.label} · readiness from current BAST rules</p></div>
        </div>

        <div className="talent-directory-summary" aria-label="Talent directory summary">
          <div><span>Active talents</span><strong>{data.summary.active_talents}</strong></div>
          <div><span>BAST ready</span><strong>{data.summary.bast_ready}</strong><small>{percentage(data.summary.bast_ready, data.summary.active_talents)}</small></div>
          <div><span>Need attention</span><strong>{data.summary.need_attention}</strong></div>
          <div><span>Teams</span><strong>2</strong><small>{developerCount} Developer · {iotCount} IoT Ops</small></div>
        </div>

        <section className="panel talent-directory-panel">
          <div className="talent-directory-tabs" role="tablist" aria-label="Talent views">
            <button type="button" role="tab" aria-selected={tab === "directory"} className={tab === "directory" ? "active" : ""} onClick={() => setTab("directory")}>Directory</button>
            <button type="button" role="tab" aria-selected={tab === "links"} className={tab === "links" ? "active" : ""} onClick={() => setTab("links")}>Talent URLs</button>
          </div>

          <div className="panel-title-row">
            <div>
              <h2>{tab === "directory" ? "Talent directory" : "Talent Mobile URLs"}</h2>
              <span>{visible.length} of {data.readiness.length} talents · {data.period.label}</span>
            </div>
            {tab === "links" ? (
              <div>
                <button className="secondary-button" type="button" onClick={() => void copyVisibleTalentLinks()} disabled={linksLoading || visible.length === 0}>
                  {copiedListCount === null ? "Copy All Talent Links" : `Copied ${copiedListCount} links`}
                </button>{" "}
                <button className="secondary-button" type="button" onClick={() => void loadLinks()} disabled={linksLoading}>
                  {linksLoading ? "Generating…" : "Refresh URLs"}
                </button>
              </div>
            ) : null}
          </div>

          {tab === "links" ? (
            <div className="talent-url-note">
              <strong>Link personal · berlaku {validityLabel(links?.ttl_seconds)}.</strong>
              <span>URL tersedia untuk semua Talent pada hasil filter dan mengikuti periode aktif. Copy All Talent Links menyalin nama + URL sesuai filter saat ini, siap ditempel ke grup.</span>
            </div>
          ) : null}

          <div className="toolbar directory-toolbar">
            <div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search talent directory" /></div>
            <select value={team} onChange={(event) => setTeam(event.target.value as TeamFilter)} aria-label="Filter by team">
              <option value="all">All teams</option><option value="Developer">Developer</option><option value="IoT Operations">IoT Operations</option>
            </select>
            <select value={state} onChange={(event) => setState(event.target.value as StateFilter)} aria-label="Filter by readiness">
              <option value="all">All readiness</option><option value="attention">Need attention</option><option value="complete">Ready</option>
            </select>
          </div>

          {visible.length === 0 ? <div className="empty-state">No talents match the current filters.</div> : null}
          {tab === "links" && linksError ? <div className="empty-state">Talent URLs gagal dimuat. Coba Refresh URLs.</div> : null}

          {tab === "directory" ? (
            <>
              <div className="desktop-table-wrap">
                <table className="data-table talent-directory-table">
                  <thead><tr><th>Talent</th><th>Team</th><th>Attendance</th><th>Timesheet</th><th>Task</th><th>Evidence</th><th>Overall</th><th aria-label="Open" /></tr></thead>
                  <tbody>{visible.map((talent) => (
                    <tr key={talent.employee_id} onClick={() => onOpenTalent(talent.nrp)}>
                      <td><div className="talent-name">{talent.name}</div><div className="cell-muted">{talent.nrp}</div></td>
                      <td>{talent.role}</td>
                      <td><StatusBadge state={talent.checks.attendance.state} compact /></td>
                      <td><StatusBadge state={talent.checks.timesheet.state} compact /></td>
                      <td><StatusBadge state={talent.checks.task.state} compact /></td>
                      <td><StatusBadge state={talent.checks.evidence.state} compact /></td>
                      <td><StatusBadge state={talent.overall_state} compact /></td>
                      <td><button className="row-open" type="button" aria-label={`Open ${talent.name}`} onClick={(event) => { event.stopPropagation(); onOpenTalent(talent.nrp); }}><ChevronIcon /></button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>

              <div className="mobile-operational-list slice2-mobile-list">
                {visible.map((talent) => (
                  <button className="talent-mobile-card" type="button" key={talent.employee_id} onClick={() => onOpenTalent(talent.nrp)}>
                    <div className="talent-mobile-head"><div><strong>{talent.name}</strong><span>{talent.nrp} · {talent.role}</span></div><StatusBadge state={talent.overall_state} compact /></div>
                    <div className="talent-mobile-checks">
                      {([['Attendance', talent.checks.attendance], ['Timesheet', talent.checks.timesheet], ['Task', talent.checks.task], ['Evidence', talent.checks.evidence]] as const).map(([label, check]) => (
                        <div key={label}><span>{label}</span><strong className={`text-${check.state}`}>{statusLabel(check.state)}</strong></div>
                      ))}
                    </div>
                    <ChevronIcon className="talent-mobile-chevron" />
                  </button>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="desktop-table-wrap">
                <table className="data-table talent-url-table">
                  <thead><tr><th>Talent</th><th>Team</th><th>Readiness</th><th>Access</th><th>URL</th><th>Action</th></tr></thead>
                  <tbody>{visible.map((talent) => {
                    const link = linksByEmployee.get(talent.employee_id);
                    return (
                      <tr key={talent.employee_id}>
                        <td><button type="button" className="talent-url-name" onClick={() => onOpenTalent(talent.nrp)}><strong>{talent.name}</strong><span>{talent.nrp}</span></button></td>
                        <td>{talent.role}</td>
                        <td><StatusBadge state={talent.overall_state} compact /></td>
                        <td><span className={`talent-url-access ${link?.status ?? "loading"}`}>{accessLabel(link)}</span></td>
                        <td><span className="talent-url-preview">{link?.url ? "Signed Talent Mobile URL" : "—"}</span></td>
                        <td><button className="secondary-button talent-url-copy" type="button" disabled={!link?.url} onClick={() => void copyTalentLink(link)}>{copiedEmployee === talent.employee_id ? "Copied" : "Copy URL"}</button></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>

              <div className="mobile-operational-list slice2-mobile-list talent-url-mobile-list">
                {visible.map((talent) => {
                  const link = linksByEmployee.get(talent.employee_id);
                  return (
                    <article className="talent-url-mobile-card" key={talent.employee_id}>
                      <div className="talent-mobile-head"><div><strong>{talent.name}</strong><span>{talent.nrp} · {talent.role}</span></div><StatusBadge state={talent.overall_state} compact /></div>
                      <div className="talent-url-mobile-access"><span>{accessLabel(link)}</span><small>{link?.url ? `Signed · ${validityLabel(links?.ttl_seconds)}` : "Link belum tersedia"}</small></div>
                      <button className="secondary-button" type="button" disabled={!link?.url} onClick={() => void copyTalentLink(link)}>{copiedEmployee === talent.employee_id ? "Copied" : "Copy Talent URL"}</button>
                    </article>
                  );
                })}
              </div>
            </>
          )}
        </section>
      </div>

      {aiOpen ? (
        <div className="slice2-ai-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAiOpen(false); }}>
          <section className="slice2-ai-panel" role="dialog" aria-modal="true" aria-label="Ask AI about talents">
            <div className="slice2-ai-head"><div><SparkleIcon /><strong>Ask AI</strong></div><button type="button" className="icon-button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
            <p>Grounded in the selected period and deterministic readiness results.</p>
            <form onSubmit={(event) => void submitAi(event)}><textarea value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} rows={4} /><button className="primary-button" type="submit" disabled={aiLoading}>{aiLoading ? "Thinking…" : "Ask"}</button></form>
            {aiAnswer ? <div className="slice2-ai-answer">{aiAnswer}</div> : null}
            {aiUnavailable ? <div className="slice2-ai-answer muted">AI is unavailable. Readiness data above remains authoritative.</div> : null}
          </section>
        </div>
      ) : null}
    </WorkspaceFrame>
  );
}
