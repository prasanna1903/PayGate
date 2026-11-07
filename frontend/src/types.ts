export type ApiReason = {
  code: string;
  message: string;
  payroll_input_id?: string | null;
  exception_id?: string | null;
  time_entry_id?: string | null;
  export_id?: string | null;
};

export type DashboardSummary = {
  employee_count: number;
  payroll_input_count: number;
  validation_finding_count: number;
  blocked_input_count: number;
  successful_export_count: number;
  latest_validation_run: {
    run_id: string;
    started_at: string;
    finding_count: number;
    blocked_input_count: number;
    validated_input_count: number;
  } | null;
  export_options: {
    pay_group_id: string;
    pay_group_name: string;
    period_id: string;
  }[];
  recent_exports: {
    export_id: string;
    pay_group_id: string;
    period_id: string;
    status: string;
    total_net_minor: number;
    created_at: string;
  }[];
};

export type PageResult<T> = {
  total: number;
  limit: number;
  offset: number;
  items: T[];
};

export type PayrollInput = {
  payroll_input_id: string;
  employee_id: string;
  employee_name: string;
  pay_group_id: string;
  period_id: string;
  regular_hours: number;
  ot_hours: number;
  net_minor: number;
  status: string;
};

export type PayGateException = {
  exception_id: string;
  run_id: string;
  rule_id: string;
  rule_name: string;
  severity: string;
  blocking: boolean;
  status: string;
  entity_type: string;
  entity_id: string;
  employee_id: string | null;
  period_id: string | null;
  evidence: Record<string, unknown>;
  message: string | null;
};

export type Scorecard = {
  dataset: Record<string, unknown>;
  validation_run_id: string;
  overall: {
    total_planted_issues: number;
    total_detected_issues: number;
    tp: number;
    fp: number;
    fn: number;
    precision: number;
    recall: number;
    f1: number;
  };
  by_rule_id: Record<
    string,
    { tp: number; fp: number; fn: number; precision: number; recall: number; f1: number }
  >;
};

export type ValidationRun = {
  run_id: string;
  started_at: string;
  finding_count: number;
  findings: PayGateException[];
  blocked_inputs: string[];
  validated_inputs: string[];
};

export type ExportResult = {
  export_id: string;
  pay_group_id: string;
  period_id: string;
  status: "CREATED" | "RELEASED";
  line_count: number;
  total_net_minor: number;
  created_at: string;
  lines: {
    payroll_input_id: string;
    employee_id: string;
    period_id: string;
    amount_minor: number;
  }[];
};
