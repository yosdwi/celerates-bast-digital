import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { getPayrollOverview } from "../api/payroll";
import type { PayrollOverviewResponse } from "../api/payroll";
import { getCommandCenter, getSession, getTalentDetail } from "../api/talentops";
import type { CommandCenterResponse, TalentDetailResponse, TalentOpsSession } from "../api/types";
import ActionCenterPage from "../pages/ActionCenterPage";
import AttendanceGapsPage from "../pages/AttendanceGapsPage";
import BastReadinessPage from "../pages/BastReadinessPage";
import CommandCenterPage from "../pages/CommandCenterPage";
import DeliveryPage from "../pages/DeliveryPage";
import EvidencePage from "../pages/EvidencePage";
import PayrollPage from "../pages/PayrollPage";
import SettingsPage from "../pages/SettingsPage";
import SystemSyncPage from "../pages/SystemSyncPage";
import Talent360Page from "../pages/Talent360Page";
import TalentsPage from "../pages/TalentsPage";
import { PeriodControlProvider } from "./PeriodContext";
import { parsePeriodSearch, samePeriod, withPeriodQuery } from "./period";
import type { PeriodSelection } from "./period";

type Route =
  | { page: "command-center" }
  | { page: "payroll" }
  | { page: "talents" }
  | { page: "actions" }
  | { page: "attendance-gaps" }
  | { page: "bast" }
  | { page: "delivery" }
  | { page: "evidence" }
  | { page: "system" }
  | { page: "settings" }
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
  if (clean === "/admin/talentops/payroll") return { page: "payroll" };
  if (clean === "/admin/talentops/talents") return { page: "talents" };
  if (clean === "/admin/talentops/actions") return { page: "actions" };
  if (clean === "/admin/talentops/attendance-gaps") return { page: "attendance-gaps" };
  if (clean === "/admin/talentops/bast-readiness") return { page: "bast" };
  if (clean === "/admin/talentops/delivery") return { page: "delivery" };
  if (clean === "/admin/talentops/evidence") return { page: "evidence" };
  if (clean === "/admin/talentops/system-sync") return { page: "system" };
  if (clean === "/admin/talentops/settings") return { page: "settings" };
  return { page: "command-center" };
}

function replacePeriodUrl(period: Pick<PeriodSelection, "year" | "month">) {
  const next = withPeriodQuery(window.location.pathname, window.location.search, period);
  const current = `${window.location.pathname}${window.location.search}`;
  if (next !== current) {
    window.history.replaceState({}, "", `${next}${window.location.hash}`);
  }
}

function LoadingScreen() {
  return (
    <div className="boot-screen" aria-busy="true">
      <div className="boot-sidebar" />
      <main>
        <div className="boot-topbar" />
        <div className="boot-content">
          <div className="skeleton-line title" />
          <div className="skeleton-summary">
            {Array.from({ length: 4 }, (_, index) => <div key={index} />)}
          </div>
          <div className="skeleton-panel" />
          <div className="skeleton-panel large" />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<TalentOpsSession | null>(null);
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [payrollData, setPayrollData] = useState<PayrollOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [payrollLoading, setPayrollLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payrollError, setPayrollError] = useState<string | null>(null);
  const [periodPending, setPeriodPending] = useState<PeriodSelection | null>(null);
  const [periodError, setPeriodError] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [talent, setTalent] = useState<TalentDetailResponse | null>(null);
  const [talentLoading, setTalentLoading] = useState(false);
  const [talentError, setTalentError] = useState<string | null>(null);
  const periodRequestId = useRef(0);
  const payrollRequestId = useRef(0);

  const loadPayroll = useCallback(async (
    selection?: PeriodSelection,
    updateUrl = true,
  ) => {
    const requestId = payrollRequestId.current + 1;
    payrollRequestId.current = requestId;
    setPayrollLoading(true);
    setPayrollError(null);
    try {
      const nextPayroll = selection
        ? await getPayrollOverview(selection.year, selection.month)
        : await getPayrollOverview();
      if (requestId !== payrollRequestId.current) return;
      setPayrollData(nextPayroll);
      if (updateUrl) {
        replacePeriodUrl({ year: nextPayroll.cycle.year, month: nextPayroll.cycle.month });
      }
    } catch (reason) {
      if (requestId !== payrollRequestId.current) return;
      setPayrollError(reason instanceof Error ? reason.message : "Unable to load Payroll.");
    } finally {
      if (requestId === payrollRequestId.current) setPayrollLoading(false);
    }
  }, []);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPayrollError(null);
    try {
      const initialRoute = parseRoute(window.location.pathname);
      const requested = parsePeriodSearch(window.location.search);
      const nextSession = await getSession();
      setSession(nextSession);

      if (initialRoute.page === "payroll") {
        const nextPayroll = requested
          ? await getPayrollOverview(requested.year, requested.month)
          : await getPayrollOverview();
        setPayrollData(nextPayroll);
        replacePeriodUrl({ year: nextPayroll.cycle.year, month: nextPayroll.cycle.month });
        return;
      }

      const nextData = requested
        ? await getCommandCenter(requested.year, requested.month)
        : await getCommandCenter();
      setData(nextData);
      replacePeriodUrl(nextData.period);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Unable to load TalentOps.";
      if (parseRoute(window.location.pathname).page === "payroll") {
        setPayrollError(message);
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPeriod = useCallback(async (period: PeriodSelection, updateUrl: boolean) => {
    const requestId = periodRequestId.current + 1;
    periodRequestId.current = requestId;
    setPeriodPending(period);
    setPeriodError(null);
    try {
      const nextData = await getCommandCenter(period.year, period.month);
      if (requestId !== periodRequestId.current) return;
      setData(nextData);
      setError(null);
      if (updateUrl) replacePeriodUrl(nextData.period);
    } catch (reason) {
      if (requestId !== periodRequestId.current) return;
      setPeriodError(
        reason instanceof Error
          ? `Unable to load the selected period: ${reason.message}`
          : "Unable to load the selected period. The previous period remains active.",
      );
    } finally {
      if (requestId === periodRequestId.current) setPeriodPending(null);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    const handlePopState = () => {
      const nextRoute = parseRoute(window.location.pathname);
      setRoute(nextRoute);
      const requested = parsePeriodSearch(window.location.search);

      if (nextRoute.page === "payroll") {
        void loadPayroll(requested ?? undefined, false);
        return;
      }

      if (!data) {
        void loadPeriod(
          requested ?? {
            year: new Date().getFullYear(),
            month: new Date().getMonth() + 1,
          },
          false,
        );
        return;
      }
      if (!requested) {
        replacePeriodUrl(data.period);
        return;
      }
      if (!samePeriod(requested, data.period)) {
        void loadPeriod(requested, false);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [data, loadPayroll, loadPeriod]);

  const detailKey = useMemo(
    () => route.page === "talent" && data
      ? `${route.nrp}:${data.period.year}:${data.period.month}`
      : null,
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
        if (!cancelled) {
          setTalentError(
            reason instanceof Error ? reason.message : "Unable to load talent detail.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setTalentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [data, detailKey, route]);

  function navigate(path: string) {
    const nextRoute = parseRoute(path);
    const selected = nextRoute.page === "payroll"
      ? payrollData?.cycle
      : data?.period ?? payrollData?.cycle;
    const target = selected
      ? withPeriodQuery(path, window.location.search, selected)
      : path;
    const current = `${window.location.pathname}${window.location.search}`;
    if (current !== target) window.history.pushState({}, "", target);
    setRoute(nextRoute);

    if (nextRoute.page === "payroll") {
      if (!payrollData) {
        const requested = parsePeriodSearch(window.location.search);
        void loadPayroll(requested ?? undefined, true);
      }
      return;
    }

    if (!data) {
      const requested = parsePeriodSearch(window.location.search);
      void loadPeriod(
        requested ?? {
          year: new Date().getFullYear(),
          month: new Date().getMonth() + 1,
        },
        true,
      );
    }
  }

  function openTalent(nrp: string) {
    navigate(`/admin/talentops/talents/${encodeURIComponent(nrp)}`);
  }

  function changePeriod(period: PeriodSelection) {
    if (!data || periodPending) return;
    if (samePeriod(period, data.period)) {
      setPeriodError(null);
      return;
    }
    void loadPeriod(period, true);
  }

  async function refresh() {
    if (!data || refreshing || periodPending) return;
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
  if (!session) {
    return (
      <main className="fatal-state">
        <div>
          <h1>TalentOps unavailable</h1>
          <p>{error ?? payrollError ?? "TalentOps could not load the current session."}</p>
          <button className="primary-button" type="button" onClick={() => void bootstrap()}>
            Retry
          </button>
        </div>
      </main>
    );
  }

  if (route.page === "payroll") {
    if (payrollLoading) return <LoadingScreen />;
    if (!payrollData) {
      return (
        <main className="fatal-state">
          <div>
            <h1>Payroll unavailable</h1>
            <p>{payrollError ?? "Payroll attendance data could not be loaded."}</p>
            <button className="primary-button" type="button" onClick={() => void loadPayroll()}>
              Retry
            </button>
          </div>
        </main>
      );
    }
    return <PayrollPage session={session} data={payrollData} onNavigate={navigate} />;
  }

  if (!data && periodPending) return <LoadingScreen />;

  if (!data) {
    return (
      <main className="fatal-state">
        <div>
          <h1>TalentOps unavailable</h1>
          <p>{error ?? "TalentOps could not load the current data."}</p>
          <button className="primary-button" type="button" onClick={() => void bootstrap()}>
            Retry
          </button>
        </div>
      </main>
    );
  }

  let page: ReactNode;
  if (route.page === "talents") {
    page = (
      <TalentsPage
        session={session}
        data={data}
        onNavigate={navigate}
        onOpenTalent={openTalent}
      />
    );
  } else if (route.page === "actions") {
    page = (
      <ActionCenterPage
        session={session}
        data={data}
        onNavigate={navigate}
        onOpenTalent={openTalent}
      />
    );
  } else if (route.page === "attendance-gaps") {
    page = <AttendanceGapsPage session={session} data={data} onNavigate={navigate} />;
  } else if (route.page === "bast") {
    page = (
      <BastReadinessPage
        session={session}
        data={data}
        onNavigate={navigate}
        onOpenTalent={openTalent}
      />
    );
  } else if (route.page === "delivery") {
    page = (
      <DeliveryPage
        session={session}
        data={data}
        onNavigate={navigate}
        onOpenTalent={openTalent}
      />
    );
  } else if (route.page === "evidence") {
    page = (
      <EvidencePage
        session={session}
        data={data}
        onNavigate={navigate}
        onOpenTalent={openTalent}
      />
    );
  } else if (route.page === "system") {
    page = <SystemSyncPage session={session} data={data} onNavigate={navigate} />;
  } else if (route.page === "settings") {
    page = <SettingsPage session={session} data={data} onNavigate={navigate} />;
  } else if (route.page === "talent") {
    const talentHasWrongPeriod = talent ? !samePeriod(talent.period, data.period) : false;
    if (talentLoading || talentHasWrongPeriod) {
      page = <LoadingScreen />;
    } else if (!talent) {
      page = (
        <main className="fatal-state">
          <div>
            <h1>Talent detail unavailable</h1>
            <p>{talentError ?? "The selected talent could not be loaded."}</p>
            <button
              className="primary-button"
              type="button"
              onClick={() => navigate("/admin/talentops/talents")}
            >
              Back to Talents
            </button>
          </div>
        </main>
      );
    } else {
      page = (
        <Talent360Page
          session={session}
          commandCenter={data}
          talent={talent}
          onNavigate={navigate}
          onBack={() => navigate("/admin/talentops/talents")}
        />
      );
    }
  } else {
    page = (
      <>
        {error ? <div className="refresh-error" role="status">{error}</div> : null}
        <CommandCenterPage
          session={session}
          data={data}
          refreshing={refreshing}
          onRefresh={() => void refresh()}
          onNavigate={navigate}
          onOpenTalent={openTalent}
        />
      </>
    );
  }

  return (
    <PeriodControlProvider
      value={{
        period: data.period,
        pending: periodPending,
        loading: periodPending !== null,
        error: periodError,
        onChange: changePeriod,
      }}
    >
      {page}
    </PeriodControlProvider>
  );
}
