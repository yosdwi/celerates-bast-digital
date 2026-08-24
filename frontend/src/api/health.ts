export interface HealthProbe {
  path: string;
  ok: boolean;
  httpStatus: number | null;
  status: string;
}

async function probe(path: string): Promise<HealthProbe> {
  try {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    let status = response.ok ? "ok" : "unavailable";
    try {
      const payload = (await response.json()) as { status?: unknown };
      if (typeof payload.status === "string" && payload.status.trim()) status = payload.status;
    } catch {
      // Keep the HTTP-derived status when the response is not JSON.
    }
    return { path, ok: response.ok, httpStatus: response.status, status };
  } catch {
    return { path, ok: false, httpStatus: null, status: "unreachable" };
  }
}

export async function getRuntimeHealth(): Promise<{ live: HealthProbe; ready: HealthProbe }> {
  const [live, ready] = await Promise.all([probe("/health/live"), probe("/health/ready")]);
  return { live, ready };
}
