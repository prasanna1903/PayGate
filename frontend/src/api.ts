import type {
  ApiReason,
  DashboardSummary,
  ExportResult,
  PageResult,
  PayGateException,
  PayrollInput,
  Scorecard,
  ValidationRun,
} from "./types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  reasons: ApiReason[];

  constructor(message: string, status: number, reasons: ApiReason[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reasons = reasons;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      `Could not connect to PayGate API at ${apiBaseUrl}. Check that the backend is running.`,
      0,
    );
  }

  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const data = body as { message?: string; detail?: string; reasons?: ApiReason[] };
    throw new ApiError(
      data.message || data.detail || `The API request failed (${response.status}).`,
      response.status,
      data.reasons || [],
    );
  }
  return body as T;
}

export const api = {
  dashboard: () => request<DashboardSummary>("/dashboard/summary"),
  inputs: (limit: number, offset: number, status: string, query: string) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.set("status", status);
    if (query.trim()) params.set("query", query.trim());
    return request<PageResult<PayrollInput>>(`/payroll-inputs?${params}`);
  },
  exceptions: (limit: number, offset: number, status: string, query: string) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.set("status", status);
    if (query.trim()) params.set("query", query.trim());
    return request<PageResult<PayGateException>>(`/exceptions?${params}`);
  },
  scorecard: () => request<Scorecard>("/evaluation/scorecard"),
  runValidation: () =>
    request<ValidationRun>("/validation/runs", { method: "POST" }),
  approve: (inputId: string, approverId: string, comment: string) =>
    request<{ approval_id: string; payroll_input_id: string; status: string }>(
      `/payroll-inputs/${encodeURIComponent(inputId)}/approval`,
      {
        method: "POST",
        body: JSON.stringify({ approver_id: approverId, approver_role: "HR", comment }),
      },
    ),
  waive: (exceptionId: string, approverId: string, comment: string) =>
    request<{ approval_id: string; exception_id: string; status: string }>(
      `/exceptions/${encodeURIComponent(exceptionId)}/waiver`,
      { method: "POST", body: JSON.stringify({ approver_id: approverId, comment }) },
    ),
  export: (payGroupId: string, periodId: string, requestedBy: string) =>
    request<ExportResult>("/exports", {
      method: "POST",
      body: JSON.stringify({
        pay_group_id: payGroupId,
        period_id: periodId,
        requested_by: requestedBy,
      }),
    }),
};
