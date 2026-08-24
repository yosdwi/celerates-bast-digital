import { useCallback, useEffect, useState } from "react";
import { getCommandCenter, getSession } from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import CommandCenterPage from "../pages/CommandCenterPage";

export default function App() {
  const [session, setSession] = useState<TalentOpsSession | null>(null);
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  if (loading) {
    return (
      <div className="boot-screen" aria-busy="true">
        <div className="boot-sidebar" />
        <main><div className="boot-topbar" /><div className="boot-content"><div className="skeleton-line title" /><div className="skeleton-summary">{Array.from({ length: 4 }, (_, index) => <div key={index} />)}</div><div className="skeleton-panel" /><div className="skeleton-panel large" /></div></main>
      </div>
    );
  }

  if (!session || !data) {
    return (
      <main className="fatal-state">
        <div><h1>Command Center unavailable</h1><p>{error ?? "TalentOps could not load the current data."}</p><button className="primary-button" type="button" onClick={() => void bootstrap()}>Retry</button></div>
      </main>
    );
  }

  return (
    <>
      {error ? <div className="refresh-error" role="status">{error}</div> : null}
      <CommandCenterPage session={session} data={data} refreshing={refreshing} onRefresh={() => void refresh()} />
    </>
  );
}
