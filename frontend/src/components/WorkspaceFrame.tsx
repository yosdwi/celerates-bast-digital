import { useState } from "react";
import type { ReactNode } from "react";
import type { TalentOpsSession } from "../api/types";
import {
  AlertIcon,
  CheckDocIcon,
  ExternalIcon,
  GridIcon,
  MenuIcon,
  PersonIcon,
  SearchIcon,
  SettingsIcon,
  SparkleIcon,
  SyncIcon,
  TrendIcon,
} from "./Icons";

interface Props {
  session: TalentOpsSession;
  active: "command-center" | "talents" | "actions";
  attentionCount: number;
  search: string;
  onSearch: (value: string) => void;
  onNavigate: (path: string) => void;
  onAskAi: () => void;
  children: ReactNode;
}

const NAV_ITEMS = [
  { key: "command-center", label: "Command Center", icon: GridIcon, path: "/admin/talentops/" },
  { key: "talents", label: "Talents", icon: PersonIcon, path: "/admin/talentops/talents" },
  { key: "delivery", label: "Delivery", icon: TrendIcon, path: null },
  { key: "bast", label: "BAST readiness", icon: CheckDocIcon, path: null },
  { key: "actions", label: "Actions", icon: AlertIcon, path: "/admin/talentops/actions" },
] as const;

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "PM";
}

export default function WorkspaceFrame({
  session,
  active,
  attentionCount,
  search,
  onSearch,
  onNavigate,
  onAskAi,
  children,
}: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  function navigate(path: string) {
    setSidebarOpen(false);
    onNavigate(path);
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Workspace navigation">
        <div className="nav-group">
          <div className="nav-label">Workspace</div>
          {NAV_ITEMS.map(({ key, label, icon: Icon, path }) => (
            <button
              key={key}
              className={`nav-item ${active === key ? "active" : ""}`}
              type="button"
              disabled={path === null}
              title={path === null ? "Available in a later slice" : undefined}
              onClick={() => path && navigate(path)}
            >
              <Icon className="nav-icon" />
              <span>{label}</span>
              {key === "actions" && attentionCount > 0 ? <span className="nav-count">{attentionCount}</span> : null}
            </button>
          ))}
        </div>
        <div className="nav-group">
          <div className="nav-label">Operations</div>
          <button className="nav-item" type="button" disabled title="Available in a later slice"><SyncIcon className="nav-icon" />System &amp; sync</button>
          <button className="nav-item" type="button" disabled title="Use the existing NocoDB Data Workspace"><ExternalIcon className="nav-icon" />Data workspace</button>
        </div>
        <div className="sidebar-foot"><button className="nav-item" type="button" disabled title="Available in a later slice"><SettingsIcon className="nav-icon" />Settings</button></div>
      </aside>
      <button className={`sidebar-overlay ${sidebarOpen ? "open" : ""}`} type="button" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />

      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-only" type="button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><MenuIcon /></button>
          <button className="environment-selector desktop-only" type="button" disabled>TalentOps Production <span>▾</span></button>
          <div className={`global-search ${searchOpen ? "open" : ""}`}>
            <button className="search-toggle" type="button" aria-label="Search talents" onClick={() => setSearchOpen((value) => !value)}><SearchIcon /></button>
            <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search talents, NRP, or team" aria-label="Search talents" />
          </div>
          <button className="ask-ai-button desktop-only" type="button" onClick={onAskAi}><SparkleIcon />Ask AI</button>
          <button className="icon-button ai-mobile mobile-only" type="button" aria-label="Ask AI" onClick={onAskAi}><SparkleIcon /></button>
          <div className="topbar-right"><div className="avatar" title={session.user.name}>{initials(session.user.name)}</div></div>
        </header>
        {children}
      </main>
    </div>
  );
}
