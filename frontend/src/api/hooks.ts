import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, qs } from "./client";
import type {
  AuthConfig,
  Dashboard,
  Delegation,
  Lookups,
  Me,
  NotificationItem,
  Persona,
  PolicyPayload,
  Project,
  ProjectDetail,
  RequestDetail,
  RequestSummary,
  SpendRow,
  UserBrief,
} from "./types";

export const useAuthConfig = () => useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<AuthConfig>("/api/auth/config"), staleTime: Infinity });

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me"), retry: false, staleTime: 20_000, refetchInterval: 60_000 });

export const usePersonas = (enabled: boolean) => useQuery({ queryKey: ["personas"], queryFn: () => api.get<Persona[]>("/api/auth/personas"), enabled, staleTime: Infinity });

export const useLookups = () => useQuery({ queryKey: ["lookups"], queryFn: () => api.get<Lookups>("/api/lookups"), staleTime: 300_000 });

export const useDashboard = () => useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard") });

export interface RequestFilters {
  scope?: "all" | "mine" | "waiting";
  status?: string;
  q?: string;
  category_group?: string;
  department_id?: number | string;
  project_id?: number | string;
  site_id?: number | string;
  limit?: number;
  offset?: number;
}

export const useRequests = (f: RequestFilters) =>
  useQuery({ queryKey: ["requests", f], queryFn: () => api.get<{ items: RequestSummary[]; total: number }>(`/api/requests${qs({ ...f })}`), placeholderData: (prev) => prev });

export const useRequest = (ref: string | undefined) => useQuery({ queryKey: ["request", ref], queryFn: () => api.get<RequestDetail>(`/api/requests/${ref}`), enabled: !!ref });

export const useProjects = (kind?: string, includeClosed = false) =>
  useQuery({ queryKey: ["projects", kind, includeClosed], queryFn: () => api.get<Project[]>(`/api/projects${qs({ kind, include_closed: includeClosed || undefined })}`) });

export const useProject = (id: string | undefined) => useQuery({ queryKey: ["project", id], queryFn: () => api.get<ProjectDetail>(`/api/projects/${id}`), enabled: !!id });

export const useSpend = (groupBy: string, from?: string, to?: string, extra: Record<string, string | undefined> = {}) =>
  useQuery({ queryKey: ["spend", groupBy, from, to, extra], queryFn: () => api.get<{ rows: SpendRow[] }>(`/api/reports/spend${qs({ group_by: groupBy, date_from: from, date_to: to, ...extra })}`), placeholderData: (prev) => prev });

export const usePolicy = () => useQuery({ queryKey: ["policy"], queryFn: () => api.get<PolicyPayload>("/api/admin/policy") });

export const useNotifications = (enabled: boolean) => useQuery({ queryKey: ["notifications"], queryFn: () => api.get<NotificationItem[]>("/api/notifications"), enabled });

export const useDelegations = () => useQuery({ queryKey: ["delegations"], queryFn: () => api.get<{ mine: Delegation[]; covering: Delegation[]; all_current?: Delegation[] }>("/api/delegations") });

export const useEligibleStandIns = () => useQuery({ queryKey: ["stand-ins"], queryFn: () => api.get<{ rule: string; people: UserBrief[] }>("/api/delegations/eligible") });

/** Run an API call, toast the outcome and refresh what it affects. */
export function useAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, opts: { success?: string | ((r: TResult) => string); invalidate?: unknown[][]; onSuccess?: (r: TResult) => void } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      const msg = typeof opts.success === "function" ? opts.success(result) : opts.success;
      if (msg) toast.success(msg);
      for (const key of opts.invalidate ?? [["dashboard"], ["requests"], ["me"], ["notifications"]]) qc.invalidateQueries({ queryKey: key });
      opts.onSuccess?.(result);
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
