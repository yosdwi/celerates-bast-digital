import { useCallback, useEffect, useMemo, useState } from "react";
import { getCommandCenter, getSession, getTalentDetail } from "../api/talentops";
import type { CommandCenterResponse, TalentDetailResponse, TalentOpsSession } from "../api/types";
import CommandCenterPage from "../pages/CommandCenterPage";
import Talent360Page from "../pages/Talent360Page";
import TalentsPage from "../pages/TalentsPage";

type Route =
  | { page: "command-center" }
  | { page: "talents" }
  | { page: "talent"; nrp: string };

function parseRoute(pathname: string): Route {
  const clean = pathname.replace(/\/+$/, "") || "/";
  const talentMatch = clean.match(/^\/admin\/talentops\/talents\/([^/]+)$/);
  if (talentMatch?.[1]) {
    try {
      return { page: "talent", nrp: decodeURIComponent(talentMatch[1]) };
    } catch {
      return { page: "talents" };
    }
  }
  if (clean === "/admin/talentops/talents") return { page: "talents" };
  return { page: "command-center" };
}

function LoadingScreen() {
  return (
    <div className="boot-screen" aria-busy="true">
      <div className="boot-sidebar" />
      <main><div className="boot-topbar" /><div className="boot-content"><div className="skeleton-line title" /><div className="skeleton-summary">{Array.from({ length: 4 }, (_, index) => <div key={index} />)}</div><div className="skeleton-panel" /><div className="skeleton-panel large" /></div></main>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<TalentOpsSession | null>(null);
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [talent, setTalent] = useState<TalentDetailResponse | null>(null);
  const [talentLoading, setTalentLoading] = useState(false);
  const [talentError, setTalentError] = useState<string | null>(null);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSession, nextData] = await Promise.all([getSession(), getCommandCenter()]);
      setSession(nextSession);
      setData(nextData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load TalentOps.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    const handlePopState = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const detailKey = useMemo(
    () => route.page === "talent" && data ? `${route.nrp}:${data.period.year}:${data.period.month}` : null,
    [data, route],
  );

  useEffect(() => {
    if (route.page !== "talent" || !data) {
      setTalent(null);
      setTalentError(null);
      setTalentLoading(false);
      return;
    }
    let cancelled = false;
    setTalentLoading(true);
    setTalentError(null);
    setTalent(null);
    void getTalentDetail(route.nrp, data.period.year, data.period.month)
      .then((nextTalent) => {
        if (!cancelled) setTalent(nextTalent);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setTalentError(reason instanceof Error ? reason.message : "Unable to load talent detail.");
      })
      .finally(() => {
        if (!cancelled) setTalentLoading(false);
      });
    return () => { cancelled = true; };
  }, [data, detailKey, route]);

  function navigate(path: string) {
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setRoute(parseRoute(path));
  }

  function openTalent(nrp: string) {
    navigate(`/admin/talentops/talents/${encodeURIComponent(nrp)}`);
  }

  async function refresh() {
    if (!data || refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      setData(await getCommandCenter(data.period.year, data.period.month));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to refresh Command Center.");
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) return <LoadingScreen />;

  if (!session || !data) {
    return (
      <main className="fatal-state">
        <div><h1>TalentOps unavailable</h1><p>{error ?? "TalentOps could not load the current data."}</p><button className="primary-button" type="button" onClick={() => void bootstrap()}>Retry</button></div>
      </main>
    );
  }

  if (route.page === "talents") {
    return <TalentsPage session={session} data={data} onNavigate={navigate} onOpenTalent={openTalent} />;
  }

  if (route.page === "talent") {
    if (talentLoading) return <LoadingScreen />;
    if (!talent) {
      return (
        <main className="fatal-state">
          <div><h1>Talent detail unavailable</h1><p>{talentError ?? "The selected talent could not be loaded."}</p><button className="primary-button" type="button" onClick={() => navigate("/admin/talentops/talents")}>Back to Talents</button></div>
        </main>
      );
    }
    return <Talent360Page session={session} commandCenter={data} talent={talent} onNavigate={navigate} onBack={() => navigate("/admin/talentops/talents")} />;
  }

  return (
    <>
      {error ? <div className="refresh-error" role="status">{error}</div> : null}
      <CommandCenterPage session={session} data={data} refreshing={refreshing} onRefresh={() => void refresh()} onNavigate={navigate} onOpenTalent={openTalent} />
    </>
  );
}
