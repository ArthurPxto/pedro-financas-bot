import { useEffect, useState } from "react";
import { Wordmark } from "./App";
import { ApiError, downloadCsv, getOverview, session } from "./api";
import { money, monthLabel, plural } from "./format";
import type { Bucket, Me, ReportFilters, ReportOverview } from "./types";

const STATUS_OPTIONS = [
  { value: "", label: "Contabilizados" },
  { value: "submitted", label: "Aguardando aprovação" },
  { value: "approved", label: "Aprovados" },
  { value: "reimbursed", label: "Reembolsados" },
  { value: "rejected", label: "Rejeitados" },
];

export function Dashboard({ me, onSignedOut }: { me: Me; onSignedOut: () => void }) {
  const [filters, setFilters] = useState<ReportFilters>({});
  const [data, setData] = useState<ReportOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [exporting, setExporting] = useState(false);

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
      </main>
    </div>
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
