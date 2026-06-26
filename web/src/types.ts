// Espelha os modelos da API (src/adapters/web/api.py + report_service.py).

export interface Me {
  user_id: number;
  org_id: number;
  display_name: string;
  is_admin: boolean;
}

export interface Bucket {
  key: string;
  total: number;
  count: number;
}

export interface ReportOverview {
  total: number;
  count: number;
  by_category: Bucket[];
  by_cost_center: Bucket[];
  by_user: Bucket[];
  by_month: Bucket[];
}

export interface ReportFilters {
  from?: string; // YYYY-MM-DD
  to?: string; // YYYY-MM-DD
  status?: string; // status da nota (aberta/fechada/aprovada/rejeitada/paga) ou ""
}

export interface NotaSummary {
  id: number;
  numero: number | null;
  competencia: string; // YYYY-MM-DD (1º do mês de competência)
  status: string;
  vencimento: string | null;
  author: string;
}
