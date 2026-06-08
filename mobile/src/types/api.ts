// ── Shared ──

export type TransactionType = 'income' | 'expense' | 'savings';

// ── Onboarding ──

export interface OnboardingStatus {
  has_household: boolean;
  has_income_category: boolean;
  has_expense_category: boolean;
  has_savings_category: boolean;
  is_ready: boolean;
}

// ── Households ──

export interface HouseholdCreateRequest {
  household_name: string;
  display_name: string;
}

export interface HouseholdResponse {
  id: string;
  name: string;
  created_at: string;
}

export interface HouseholdMemberResponse {
  id: string;
  household_id: string;
  user_id: string;
  display_name: string;
  role: string;
  joined_at: string;
}

export interface HouseholdSettingsResponse {
  id: string;
  household_id: string;
  currency: string;
  shift_late_income: boolean;
  late_income_cutoff_day: number | null;
  created_at: string;
  updated_at: string;
}

export interface HouseholdCreateResponse {
  household: HouseholdResponse;
  member: HouseholdMemberResponse;
  settings: HouseholdSettingsResponse;
}

// ── Categories ──

export interface CategoryCreateRequest {
  type: TransactionType;
  name: string;
  icon?: string;
  sort_order?: number;
}

export interface CategoryUpdateRequest {
  name?: string;
  icon?: string | null;
  sort_order?: number;
}

export interface CategoryResponse {
  id: string;
  household_id: string;
  type: TransactionType;
  name: string;
  icon: string | null;
  sort_order: number;
  archived_at: string | null;
  created_at: string;
}

// ── Budgets ──

export interface BudgetMonthInitializeRequest {
  month: string;
}

export interface BudgetLineResponse {
  id: string;
  category_id: string;
  category_name: string;
  planned_amount: string;
  actual_amount: string;
  notes: string | null;
}

export interface BudgetLineUpdateRequest {
  planned_amount: string;
  notes?: string | null;
}

// List item — returned by GET /budgets/months (no lines field)
export interface BudgetMonthListItem {
  id: string;
  household_id: string;
  month: string;
  notes: string | null;
  is_closed: boolean;
  created_at: string;
  updated_at: string;
}

export interface BudgetMonthsListResponse {
  months: BudgetMonthListItem[];
}

// Detail — returned by GET /budgets/months/{month_id} (includes lines)
export interface BudgetMonthResponse {
  id: string;
  month: string;
  is_closed: boolean;
  lines: BudgetLineResponse[];
  created_at: string;
}

// ── Incomes ──

export interface IncomeResponse {
  id: string;
  category_id: string;
  category_name: string;
  amount: string;
  transaction_date: string;
  effective_date: string;
  budget_month: string;
  description: string | null;
  details: string | null;
  created_at: string;
}

export interface IncomesListResponse {
  incomes: IncomeResponse[];
}

// ── Manual expenses ──

export interface ExpenseCreateRequest {
  category_id: string;
  amount: number;
  transaction_date: string;
  description?: string | null;
  details?: string | null;
}

export interface ExpenseResponse {
  id: string;
  category_id: string;
  category_name: string;
  amount: string;
  transaction_date: string;
  effective_date: string;
  budget_month: string;
  description: string | null;
  details: string | null;
  created_at: string;
}

export interface IncomeCreateRequest {
  category_id: string;
  amount: string;
  transaction_date: string;
  description?: string | null;
  details?: string | null;
}

export interface IncomeUpdateRequest {
  category_id?: string;
  amount?: string;
  transaction_date?: string;
  description?: string | null;
  details?: string | null;
}

// ── Receipts ──

export type ReceiptStatus = 'uploaded' | 'processing' | 'ocr_complete' | 'reviewed' | 'posted' | 'failed';

export interface ReceiptListItem {
  id: string;
  status: ReceiptStatus;
  store_name: string | null;
  receipt_date: string | null;
  total_amount: number | null;
  file_name: string | null;
  created_at: string;
}

export interface ReceiptItemResponse {
  id: string;
  line_number: number | null;
  description: string;
  quantity: number | null;
  unit_price: number | null;
  total_price: number;
  suggested_category_id: string | null;
  suggested_category_name: string | null;
  user_confirmed_category_id: string | null;
  user_confirmed_category_name: string | null;
  confidence: number | null;
  requires_review: boolean;
  is_excluded: boolean;
}

export interface DuplicateCandidate {
  id: string;
  store_name: string | null;
  receipt_date: string | null;
  total_amount: number | null;
}

export interface ReceiptResponse {
  id: string;
  status: ReceiptStatus;
  store_name: string | null;
  receipt_date: string | null;
  total_amount: number | null;
  file_name: string | null;
  mime_type: string | null;
  image_url: string | null;
  items: ReceiptItemResponse[];
  duplicate_candidates: DuplicateCandidate[];
  created_at: string;
}

export interface ReceiptItemUpdateRequest {
  user_confirmed_category_id?: string | null;
  is_excluded?: boolean;
}

export interface ReceiptConfirmRequest {
  transaction_date?: string | null;
}

export interface ReceiptConfirmResponse {
  transaction_group_id: string;
  transactions_created: number;
  receipt_id: string;
  status: string;
  total_mismatch: boolean;
}

// ── Savings ──

export type SavingsRuleType = 'percent_of_income' | 'fixed_monthly';
export type ProposalStatus = 'pending' | 'posted' | 'rejected';

export interface SavingsRuleResponse {
  id: string;
  category_id: string;
  category_name: string;
  rule_type: SavingsRuleType;
  label: string;
  percent_value: number | null;
  fixed_amount: number | null;
  is_active: boolean;
  created_at: string;
}

export interface SavingsRulesListResponse {
  rules: SavingsRuleResponse[];
}

export interface SavingsRuleCreateRequest {
  category_id: string;
  rule_type: SavingsRuleType;
  label: string;
  percent_value?: number | null;
  fixed_amount?: number | null;
}

export interface SavingsRuleUpdateRequest {
  label?: string | null;
  percent_value?: number | null;
  fixed_amount?: number | null;
  is_active?: boolean | null;
}

export interface SavingsProposalResponse {
  id: string;
  savings_rule_id: string;
  rule_label: string;
  budget_month: string;
  proposed_amount: number;
  final_amount: number | null;
  status: ProposalStatus;
  calculation_basis: string | null;
  created_at: string;
}

export interface SavingsProposalsListResponse {
  proposals: SavingsProposalResponse[];
}

export interface ManualSavingsCreateRequest {
  category_id: string;
  amount: number;
  transaction_date: string;
  description?: string | null;
  details?: string | null;
}

export interface ManualSavingsResponse {
  id: string;
  category_id: string;
  category_name: string;
  amount: number;
  transaction_date: string;
  effective_date: string;
  budget_month: string;
  description: string | null;
  details: string | null;
  created_at: string;
}

// ── Search ──

export type TransactionSource =
  | 'manual_income'
  | 'manual_expense'
  | 'manual_savings'
  | 'receipt'
  | 'savings_proposal';

export interface ReceiptSearchResult {
  id: string;
  store_name: string | null;
  receipt_date: string | null;
  total_amount: number | null;
  status: ReceiptStatus;
  created_at: string;
}

export interface ReceiptSearchResponse {
  results: ReceiptSearchResult[];
  total: number;
}

export interface TransactionSearchResult {
  id: string;
  type: TransactionType;
  source: TransactionSource;
  category_id: string;
  category_name: string;
  amount: number;
  description: string | null;
  transaction_date: string;
  effective_date: string;
  store_name: string | null;
  created_at: string;
}

export interface TransactionSearchResponse {
  results: TransactionSearchResult[];
  total: number;
}

// ── Invites ──

export type InviteStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export interface InviteCreateRequest {
  email: string;
}

export interface InviteCreateResponse {
  id: string;
  household_id: string;
  email: string;
  token: string;
  status: InviteStatus;
  expires_at: string;
  created_at: string;
}

export interface InviteSummary {
  id: string;
  email: string;
  status: InviteStatus;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface InviteListResponse {
  invites: InviteSummary[];
}

export interface InviteLookupRequest {
  token: string;
}

export interface InviteLookupResponse {
  household_name: string;
  email: string;
  expires_at: string;
  status: InviteStatus;
}

export interface InviteAcceptRequest {
  token: string;
  display_name: string;
}

export interface InviteAcceptResponse {
  household: HouseholdResponse;
  member: HouseholdMemberResponse;
}

export interface HouseholdSettingsUpdate {
  shift_late_income?: boolean;
  late_income_cutoff_day?: number | null;
}

// ── Dashboard ──

export interface CategoryBudgetActual {
  category_id: string;
  category_name: string;
  category_type: TransactionType;
  planned: string;
  actual: string;
  remaining: string;
  is_over_budget: boolean;
}

export interface DashboardSummary {
  month: string;
  total_planned_income: string;
  total_planned_expenses: string;
  total_planned_savings: string;
  total_actual_income: string;
  total_actual_expenses: string;
  total_actual_savings: string;
  to_be_allocated: string;
  actual_balance: string;
  plan_coverage: string;
  savings_rate: string | null;
  income_categories: CategoryBudgetActual[];
  expense_categories: CategoryBudgetActual[];
  savings_categories: CategoryBudgetActual[];
}
