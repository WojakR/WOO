// API client (contract: docs/api.md). Identity on the demo = X-User-Id header, chosen in the top bar.
const USER_KEY = "asystent.userId";

export function currentUserId() {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

export function setCurrentUserId(id) {
  try {
    localStorage.setItem(USER_KEY, String(id));
  } catch {
    /* private mode – the choice lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.komunikat || `Błąd serwera (${status})`);
    this.status = status;
    this.kod = body?.kod;
    this.walidacje = body?.walidacje || [];
  }
}

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  const uid = currentUserId();
  if (uid) headers["X-User-Id"] = uid;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, { komunikat: "Brak połączenia z serwerem." });
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  me: () => request("GET", "/me"),
  users: () => request("GET", "/users"),
  meta: () => request("GET", "/meta"),
  dashboard: () => request("GET", "/dashboard"),
  evaluation: (id) => request("GET", `/evaluations/${id}`),
  patch: (id, body) => request("PATCH", `/evaluations/${id}`, body),
  scores: (id, punkty) => request("PUT", `/evaluations/${id}/scores`, { punkty }),
  additional: (id, kody) => request("PUT", `/evaluations/${id}/criteria/additional`, { kody }),
  action: (id, akcja, body = {}) => request("POST", `/evaluations/${id}/actions/${akcja}`, body),
  notes: (id) => request("GET", `/evaluations/${id}/notes`),
  evidence: (id) => request("GET", `/evaluations/${id}/evidence`),
  criteria: (sheet) => request("GET", `/criteria?arkusz=${encodeURIComponent(sheet)}`),
  draft: (id, rodzaj) => request("POST", `/evaluations/${id}/ai/draft`, { rodzaj }),
  hrPartner: (id) => request("GET", `/evaluations/${id}/hr-partner`),
  hrDecision: (signalId, status) => request("POST", `/hr-signals/${signalId}/decision`, { status }),
  clock: (body) => request("POST", "/demo/clock", body),
  reset: () => request("POST", "/demo/reset"),
};
