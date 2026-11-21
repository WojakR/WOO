// API client (contract: docs/api.md). Identity: demo = X-User-Id header chosen in the top bar;
// session mode (AUTH_MODE=session) = the HttpOnly session cookie, the header is not sent.
const USER_KEY = "asystent.userId";
let sessionMode = false;

export function setSessionMode(on) {
  sessionMode = Boolean(on);
}

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
  const uid = sessionMode ? null : currentUserId();
  if (uid) headers["X-User-Id"] = uid;
  const isForm = body instanceof FormData;  // file upload: the browser sets the multipart header
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : isForm ? body : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, { komunikat: "Brak połączenia z serwerem." });
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (res.status === 401 && sessionMode && !path.startsWith("/auth/")) {
    window.dispatchEvent(new CustomEvent("session-expired"));
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  authStatus: () => request("GET", "/auth/status"),
  login: (login, haslo) => request("POST", "/auth/login", { login, haslo }),
  logout: () => request("POST", "/auth/logout"),
  me: () => request("GET", "/me"),
  users: () => request("GET", "/users"),
  meta: () => request("GET", "/meta"),
  dashboard: () => request("GET", "/dashboard"),
  evaluation: (id) => request("GET", `/evaluations/${id}`),
  startEvaluation: (body) => request("POST", "/evaluations", body),
  absences: (employeeId) => request("GET", `/employees/${employeeId}/absences`),
  addAbsence: (employeeId, body) => request("POST", `/employees/${employeeId}/absences`, body),
  employees: (query = "") => request("GET", `/employees${query ? `?${query}` : ""}`),
  employee: (id) => request("GET", `/employees/${id}`),
  employeeHistory: (id) => request("GET", `/employees/${id}/evaluations`),
  importEmployees: (file, { podglad = false, uruchom_cykle = false } = {}) => {
    const form = new FormData();
    form.append("file", file);
    return request("POST", `/admin/employees/import?podglad=${podglad}&uruchom_cykle=${uruchom_cykle}`, form);
  },
  positionChange: (employeeId, body) => request("POST", `/employees/${employeeId}/position-changes`, body),
  hrTasks: () => request("GET", "/kadry/zadania"),
  audit: (id) => request("GET", `/evaluations/${id}/audit`),
  requestDeadlineChange: (id, body) => request("POST", `/evaluations/${id}/deadline-changes`, body),
  allDeadlineChanges: (status = "") => request("GET", `/deadline-changes${status ? `?status=${status}` : ""}`),
  decideDeadlineChange: (id, body) => request("POST", `/deadline-changes/${id}/decision`, body),
  evaluatorAbsence: (body) => request("POST", "/evaluator-absences", body),
  deadlineChanges: (id) => request("GET", `/evaluations/${id}/deadline-changes`),
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
  myReminders: () => request("GET", "/me/przypomnienia"),
  setMyReminders: (body) => request("PUT", "/me/przypomnienia", body),
  resetMyReminders: () => request("DELETE", "/me/przypomnienia"),
  officeReminders: () => request("GET", "/ustawienia/przypomnienia"),
  setOfficeReminders: (body) => request("PUT", "/ustawienia/przypomnienia", body),
  reminderPlan: (id) => request("GET", `/evaluations/${id}/przypomnienia`),
  notifications: () => request("GET", "/notifications"),
  rules: () => request("GET", "/ustawienia/reguly"),
  setRules: (body) => request("PUT", "/ustawienia/reguly", body),
  resetRules: () => request("DELETE", "/ustawienia/reguly"),
  office: () => request("GET", "/ustawienia/urzad"),
  setOffice: (body) => request("PUT", "/ustawienia/urzad", body),
  myAssistant: () => request("GET", "/me/asystent"),
  setMyAssistant: (body) => request("PUT", "/me/asystent", body),
  readNotification: (id) => request("POST", `/notifications/${id}/read`),
};
