import { useEffect, useState } from "react";
import { Wordmark } from "./App";
import { ApiError, downloadCsv, getNotas, getOverview, session } from "./api";
import { money, monthLabel, plural } from "./format";
import type { Bucket, Me, NotaSummary, ReportFilters, ReportOverview } from "./types";

const NOTA_LABELS: Record<string, string> = {
  aberta: "aberta",
  fechada: "aguardando",
  aprovada: "aprovada",
  rejeitada: "rejeitada",
  paga: "paga",
};

// Filtra os itens pelo status da NOTA a que pertencem (Fase 5).
const STATUS_OPTIONS = [
  { value: "", label: "Todas as notas" },
  { value: "fechada", label: "Aguardando aprovação" },
  { value: "aprovada", label: "Aprovadas" },
  { value: "paga", label: "Pagas" },
  { value: "rejeitada", label: "Rejeitadas" },
];

export function Dashboard({ me, onSignedOut }: { me: Me; onSignedOut: () => void }) {
  const [filters, setFilters] = useState<ReportFilters>({});
  const [data, setData] = useState<ReportOverview | null>(null);
  const [notas, setNotas] = useState<NotaSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    getNotas()
      .then(setNotas)
      .catch(() => {
        /* lista de notas é complementar; ignora falha sem derrubar o painel */
      });
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    getOverview(filters)
      .then((d) => active && setData(d))
      .catch((e) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 401) {
          session.clear();
          onSignedOut();
        } else {
          setError("Não consegui carregar os relatórios. Tente de novo.");
        }
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [filters, onSignedOut]);

  const set = (patch: Partial<ReportFilters>) => setFilters((f) => ({ ...f, ...patch }));

  const onExport = async () => {
    setExporting(true);
    try {
      await downloadCsv(filters);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <Wordmark />
        <div className="topbar-right">
          <span className="org-name">{me.display_name}</span>
          <button
            className="btn-ghost"
            onClick={() => {
              session.clear();
              onSignedOut();
            }}
          >
            Sair
          </button>
        </div>
      </header>

      <main className="content">
        <section className="hero">
          <p className="hero-eyebrow">Total no período</p>
          <h1 className="hero-total">{data ? money(data.total) : "—"}</h1>
          <div className="hero-rule" />
          <p className="hero-sub">
            {loading
              ? "Somando…"
              : data
                ? plural(data.count, "gasto contabilizado", "gastos contabilizados")
                : "—"}
          </p>

          <div className="filters">
            <label className="field">
              <span>De</span>
              <input
                type="date"
                value={filters.from ?? ""}
                onChange={(e) => set({ from: e.target.value || undefined })}
              />
            </label>
            <label className="field">
              <span>Até</span>
              <input
                type="date"
                value={filters.to ?? ""}
                onChange={(e) => set({ to: e.target.value || undefined })}
              />
            </label>
            <label className="field">
              <span>Status</span>
              <select
                value={filters.status ?? ""}
                onChange={(e) => set({ status: e.target.value || undefined })}
              >
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn-primary" onClick={onExport} disabled={exporting || !data?.count}>
              {exporting ? "Exportando…" : "Exportar CSV"}
            </button>
          </div>
        </section>

        {error && <p className="error">{error}</p>}

        {data && data.count === 0 && !loading && (
          <p className="empty">Nenhum gasto no período. Ajuste o filtro de datas ou status.</p>
        )}

        {data && data.count > 0 && (
          <div className="grid">
            <Ledger title="Por categoria" buckets={data.by_category} />
            <Ledger title="Por centro de custo" buckets={data.by_cost_center} />
            <Ledger title="Por pessoa" buckets={data.by_user} />
            <Ledger title="Por mês" buckets={data.by_month} labeller={monthLabel} />
          </div>
        )}

        {notas.length > 0 && <NotasCard notas={notas} />}
      </main>
    </div>
  );
}

function NotasCard({ notas }: { notas: NotaSummary[] }) {
  return (
    <section className="card notas-card">
      <h2 className="card-title">Notas de débito</h2>
      <ul className="rank">
        {notas.map((n) => (
          <li className="nota-row" key={n.id}>
            <span className="nota-id">{n.numero ? `#${n.numero}` : "rascunho"}</span>
            <span className="nota-mid">
              {monthLabel(n.competencia.slice(0, 7))} · {n.author}
            </span>
            <span className={`nota-chip chip-${n.status}`}>
              {NOTA_LABELS[n.status] ?? n.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Ledger({
  title,
  buckets,
  labeller,
}: {
  title: string;
  buckets: Bucket[];
  labeller?: (key: string) => string;
}) {
  const max = Math.max(...buckets.map((b) => b.total), 1);
  return (
    <section className="card">
      <h2 className="card-title">{title}</h2>
      <ul className="rank">
        {buckets.map((b) => (
          <li className="rank-row" key={b.key}>
            <div className="rank-head">
              <span className="rank-label">{labeller ? labeller(b.key) : b.key}</span>
              <span className="rank-value">{money(b.total)}</span>
            </div>
            <div className="rank-bar">
              <i style={{ width: `${(b.total / max) * 100}%` }} />
            </div>
            <span className="rank-count">{plural(b.count, "lançamento", "lançamentos")}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
