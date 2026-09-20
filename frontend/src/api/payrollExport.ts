import { apiFetch, apiFetchResponse } from "./client";

export type PayrollExportReportType = "developer" | "shifting";

export interface PayrollExportHistoryItem {
  export_id: string;
  cycle_id: string;
  cycle_label: string;
  start_date: string;
  end_date: string;
  exported_at: string;
  exported_by: string;
  report_type: PayrollExportReportType;
  role_filter: string;
  employee_filter: string | null;
  filename: string;
  result: string;
  row_count: number;
}

export interface PayrollExportHistoryResponse {
  cycle_id: string;
  cycle_label: string;
  start_date: string;
  end_date: string;
  items: PayrollExportHistoryItem[];
}

export interface PayrollExportDownload {
  blob: Blob;
  filename: string;
  exportId: string | null;
  rowCount: number | null;
}

function selectedCycleQuery(year: number, month: number): string {
  return `year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}`;
}

function responseFilename(response: Response): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8) return decodeURIComponent(utf8.replace(/^"|"$/g, ""));
  const simple = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return simple?.trim() || "payroll-attendance.csv";
}

export function getPayrollExportHistory(
  year: number,
  month: number,
): Promise<PayrollExportHistoryResponse> {
  return apiFetch<PayrollExportHistoryResponse>(
    `/api/talentops/v1/payroll/exports/history?${selectedCycleQuery(year, month)}`,
  );
}

export async function exportPayrollAttendance(
  csrfToken: string,
  year: number,
  month: number,
  reportType: PayrollExportReportType,
): Promise<PayrollExportDownload> {
  const response = await apiFetchResponse(
    `/api/talentops/v1/payroll/exports?${selectedCycleQuery(year, month)}`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ report_type: reportType }),
    },
  );
  const rowCountHeader = response.headers.get("x-payroll-row-count");
  const parsedRowCount = rowCountHeader === null ? Number.NaN : Number(rowCountHeader);
  return {
    blob: await response.blob(),
    filename: responseFilename(response),
    exportId: response.headers.get("x-payroll-export-id"),
    rowCount: Number.isFinite(parsedRowCount) ? parsedRowCount : null,
  };
}
