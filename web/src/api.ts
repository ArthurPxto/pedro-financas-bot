import type { Me, ReportFilters, ReportOverview } from "./types";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "pf_session";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const session = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

function authHeaders(): HeadersInit {
  const t = session.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Troca o token do magic-link por um token de sessão e o guarda. */
export async function exchange(loginToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/auth/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: loginToken }),
  });
  const { session_token } = await asJson<{ session_token: string }>(res);
  session.set(session_token);
}

export async function getMe(): Promise<Me> {
  return asJson<Me>(await fetch(`${API_URL}/auth/me`, { headers: authHeaders() }));
}

function query(f: ReportFilters): string {
  const p = new URLSearchParams();
  if (f.from) p.set("from", f.from);
  if (f.to) p.set("to", f.to);
  if (f.status) p.set("status", f.status);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function getOverview(f: ReportFilters): Promise<ReportOverview> {
  return asJson<ReportOverview>(
    await fetch(`${API_URL}/reports/overview${query(f)}`, { headers: authHeaders() }),
  );
}

/** Baixa o CSV com o Bearer (não dá para usar <a href> direto por causa do header). */
export async function downloadCsv(f: ReportFilters): Promise<void> {
  const res = await fetch(`${API_URL}/reports/export.csv${query(f)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new ApiError(res.status, "Falha ao exportar.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `gastos-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
