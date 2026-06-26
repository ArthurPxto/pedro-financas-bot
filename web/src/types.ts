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
  status?: string; // valor único do enum, ou "" para os contabilizados
}
