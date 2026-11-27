export type Status = "draft" | "pending" | "returned" | "approved" | "rejected" | "withdrawn" | "cancelled" | "closed";
export type Group = "it" | "travel" | "general";
export type FinanceStateName = "awaiting_invoice" | "awaiting_payment" | "paid" | "closed";

export interface UserBrief {
  id: number;
  name: string;
  email: string;
  job_title: string | null;
  initials: string;
  department: string | null;
  site: string | null;
  is_active: boolean;
}

export interface Capabilities {
  sees_everything: boolean;
  is_finance: boolean;
  can_view_finance: boolean;
  can_manage_policy: boolean;
  can_manage_reference_data: boolean;
  can_manage_people: boolean;
  can_view_audit: boolean;
  is_manager: boolean;
  is_department_head: boolean;
  is_approver: boolean;
  can_create_projects: boolean;
  read_only: boolean;
}

export interface Delegation {
  id: number;
  principal: UserBrief;
  delegate: UserBrief;
  starts_on: string;
  ends_on: string;
  note: string | null;
  state: "active" | "scheduled" | "expired" | "ended";
  created_at: string;
  revoked_at: string | null;
}

export interface Me {
  user: UserBrief & { roles: string[]; manager: UserBrief | null };
  capabilities: Capabilities;
  my_cover: Delegation[];
  covering: Delegation[];
  counts: { waiting_for_me: number; unread_notifications: number };
  auth_method: "demo" | "oidc" | null;
  demo_mode: boolean;
}

export interface AuthConfig {
  app_name: string;
  environment: string;
  demo_mode: boolean;
  sso_enabled: boolean;
  sso_provider: string;
}

export interface Persona {
  user: UserBrief;
  roles: string[];
  headline: string;
  blurb: string;
}

/** Invoiced spend above the approval, while it's still open. */
export interface Excess {
  over_usd: number;
  invoiced_usd: number;
  approved_usd: number;
  currency: string;
  /** In the approved currency, when every invoice is in it. */
  over_amount: number | null;
  invoiced_amount: number | null;
  approved_amount: number | null;
  invoice_id: number;
  invoice_number: string;
  note: string | null;
}

export interface NextStep {
  kind: "requester" | "approval" | "finance" | "corrected_invoice";
  owner: UserBrief | null;
  label: string;
}

export interface FinanceState {
  state: FinanceStateName;
  invoiced_usd: number;
  paid_usd: number;
  remaining_usd: number;
  invoice_count: number;
  over_approval: boolean;
  excess: Excess | null;
  next_step: NextStep | null;
}

/** A change to an approved request that is waiting for approval. */
export interface PendingChange {
  approved_total_amount: number;
  approved_currency: string;
  approved_total_usd: number;
  requested_total_amount: number;
  requested_currency: string;
  requested_total_usd: number;
  change_pct: number | null;
  reason: string | null;
}

export interface RequestSummary {
  id: number;
  ref: string;
  title: string;
  status: Status;
  requester: UserBrief;
  department: string | null;
  site: string | null;
  category: { id: number; name: string; group: Group } | null;
  project: { id: number; name: string; kind: "project" | "trip"; code: string } | null;
  supplier: string | null;
  currency: string;
  amount: number;
  total_amount: number;
  total_usd: number;
  approved_total_usd: number | null;
  approved_total_amount: number | null;
  payment_type: "one_off" | "recurring";
  billing_period: "monthly" | "quarterly" | "annually" | null;
  term_months: number | null;
  is_confidential: boolean;
  has_quote: boolean;
  no_quote_reason: string | null;
  amendment_in_progress: boolean;
  change: PendingChange | null;
  waiting_for: UserBrief | null;
  waiting_reasons: string[];
  waiting_since: string | null;
  finance: FinanceState | null;
  revision: number;
  created_at: string;
  submitted_at: string | null;
  approved_at: string | null;
  decided_at: string | null;
  updated_at: string;
}

export interface Step {
  id: number;
  revision: number;
  sequence: number;
  status: "waiting" | "pending" | "approved" | "rejected" | "returned" | "skipped";
  approver: UserBrief;
  acted_by: UserBrief | null;
  on_behalf_of: UserBrief | null;
  reasons: string[];
  routing_note: string | null;
  decision_reason: string | null;
  comment: string | null;
  activated_at: string | null;
  acted_at: string | null;
  first_viewed_at: string | null;
  reminder_count: number;
  approved_content_hash: string | null;
}

export interface Change {
  field: string;
  from: unknown;
  to: unknown;
}

export interface Revision {
  number: number;
  kind: "submission" | "resubmission" | "amendment";
  status: string;
  reason: string | null;
  total_usd: number;
  content_hash: string;
  created_at: string;
  created_by: UserBrief | null;
  decided_at: string | null;
  changes: Change[];
}

export interface Attachment {
  id: number;
  kind: "quote" | "invoice" | "supporting";
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  revision: number;
  uploaded_by: UserBrief | null;
  uploaded_at: string;
  invoice_id: number | null;
}

export interface Invoice {
  id: number;
  invoice_number: string;
  invoice_date: string;
  supplier: string | null;
  currency: string;
  amount: number;
  amount_usd: number;
  status: "received" | "queried" | "paid" | "void";
  exceeds_approval: boolean;
  override_reason: string | null;
  notes: string | null;
  received_by: UserBrief | null;
  received_at: string;
  paid_by: UserBrief | null;
  paid_on: string | null;
  payment_reference: string | null;
  query_reason: string | null;
  queried_by: UserBrief | null;
  queried_at: string | null;
  query_resolution: string | null;
  replaces_invoice_number: string | null;
  void_reason: string | null;
  voided_by: UserBrief | null;
  voided_at: string | null;
  attachments: { id: number; filename: string; size_bytes: number }[];
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor: UserBrief | null;
  on_behalf_of: UserBrief | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  data: Record<string, unknown>;
  ip: string | null;
  hash: string;
  request_ref?: string | null;
}

export interface Permissions {
  can_edit: boolean;
  can_submit: boolean;
  can_withdraw: boolean;
  can_delete: boolean;
  can_decide: boolean;
  can_return: boolean;
  acting_for: string | null;
  can_amend: boolean;
  can_cancel: boolean;
  can_record_invoice: boolean;
  can_close: boolean;
  can_comment: boolean;
  can_upload: boolean;
}

export interface RequestDetail extends RequestSummary {
  description: string | null;
  needed_by: string | null;
  start_date: string | null;
  contract_end: string | null;
  fx_rate: number;
  policy_version: number | null;
  approved_revision: number | null;
  steps: Step[];
  revisions: Revision[];
  attachments: Attachment[];
  invoices: Invoice[];
  comments: { id: number; author: UserBrief; body: string; created_at: string }[];
  timeline: AuditEvent[];
  permissions: Permissions;
  amendment?: { needs_reapproval: boolean; explanation: string };
}

export interface Category {
  id: number;
  name: string;
  group: Group;
  description: string | null;
  quote_required: boolean;
  confidential_default: boolean;
}

export interface Lookups {
  categories: Category[];
  projects: { id: number; code: string; name: string; kind: "project" | "trip"; destination: string | null; start_date: string | null }[];
  departments: { id: number; name: string }[];
  sites: { id: number; name: string; country: string; currency: string }[];
  currencies: string[];
  rates: { currency: string; usd_per_unit: number; effective_date: string }[];
  default_currency: string;
  base_currency: string;
  policy: { version: number; rejection_reasons: string[]; amendment_tolerance_pct: number; rolling_term_months: number };
}

export interface SpendRow {
  key: string | number | null;
  label: string;
  count: number;
  committed_usd: number;
  pending_usd: number;
  invoiced_usd: number;
  paid_usd: number;
  kind?: "project" | "trip" | null;
  budget_usd?: number | null;
}

export interface DashboardNumbers {
  scope: "company" | "department" | "team" | "self";
  pending: { count: number; usd: number };
  committed: { month_usd: number; quarter_usd: number; year_usd: number };
  awaiting_invoice: { count: number; usd: number };
  awaiting_payment: { count: number; usd: number };
  by_group: SpendRow[];
  by_department: SpendRow[];
  top_projects: SpendRow[];
  trend: { month: string; it: number; travel: number; general: number }[];
  period: { year_start: string; today: string };
}

export interface Dashboard {
  waiting: RequestSummary[];
  /** Invoice differences where you own the next step. */
  attention: RequestSummary[];
  mine: RequestSummary[];
  numbers: DashboardNumbers;
}

export interface Project {
  id: number;
  code: string;
  name: string;
  kind: "project" | "trip";
  description: string | null;
  destination: string | null;
  start_date: string | null;
  end_date: string | null;
  budget_usd: number | null;
  is_active: boolean;
  owner: UserBrief | null;
  department: string | null;
  committed_usd: number;
  pending_usd: number;
  invoiced_usd: number;
  paid_usd: number;
  count: number;
}

export interface ProjectDetail extends Project {
  by_category: SpendRow[];
  by_department: SpendRow[];
  requests: RequestSummary[];
}

export interface RouteStepPreview {
  approver: { id: number; name: string; job_title: string | null };
  reasons: string[];
  notes: string[];
}

export interface RoutePreview {
  ready: boolean;
  policy_version?: number;
  total_amount: string;
  total_usd: string;
  fx_rate?: string;
  steps: RouteStepPreview[];
}

export interface PolicyRule {
  key: string;
  label: string;
  active: boolean;
  approver: { type: "line_manager" | "department_head" | "role" | "user"; role?: string | null; user_id?: number | null };
  when: { category_groups: Group[]; category_ids: number[]; department_ids: number[]; site_ids: number[]; min_total_usd: string | number | null };
}

export interface PolicyDocument {
  rules: PolicyRule[];
  amendment_tolerance_pct: string | number;
  reminder_after_hours: number;
  rolling_term_months: number;
  fallback_approver_role: string;
  stand_in_roles: string[];
  renewal_notice_days: number;
  rejection_reasons: string[];
}

export interface PolicyPayload {
  current: { version: number; document: PolicyDocument; created_at: string; created_by: UserBrief | null; change_note: string | null };
  versions: { version: number; created_at: string; created_by: UserBrief | null; change_note: string | null }[];
  role_labels: Record<string, string>;
  position_holders: Record<string, UserBrief | null>;
  category_groups: Group[];
}

export interface Person extends UserBrief {
  roles: string[];
  manager: UserBrief | null;
  department_id: number | null;
  site_id: number | null;
  direct_reports: number;
  external_id: string | null;
}

export interface NotificationItem {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export interface OutboxEmail {
  id: number;
  to: UserBrief | null;
  to_email: string;
  subject: string;
  kind: string;
  status: string;
  created_at: string;
  body_text: string;
}
