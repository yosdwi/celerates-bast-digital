export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function loginUrl(): string {
  return import.meta.env.DEV ? "http://127.0.0.1:8000/admin/login" : "/admin/login";
}

function redirectToLogin(): void {
  window.location.assign(loginUrl());
}

export async function apiFetchResponse(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Authentication required");
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        message = payload.detail;
      }
    } catch {
      // Preserve the status-based message when the response is not JSON.
    }
    throw new ApiError(response.status, message);
  }

  return response;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetchResponse(path, init);
  return (await response.json()) as T;
}
