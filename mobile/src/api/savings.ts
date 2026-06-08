import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  ManualSavingsCreateRequest,
  ManualSavingsResponse,
  SavingsProposalResponse,
  SavingsProposalsListResponse,
  SavingsRuleCreateRequest,
  SavingsRuleResponse,
  SavingsRuleUpdateRequest,
  SavingsRulesListResponse,
} from '@/types/api';

export function useSavingsRules() {
  return useQuery({
    queryKey: ['savings', 'rules'],
    queryFn: () => apiClient.get<SavingsRulesListResponse>('/savings/rules'),
  });
}

export function useSavingsProposals(budgetMonthId?: string) {
  return useQuery({
    queryKey: ['savings', 'proposals', { budgetMonthId }],
    queryFn: () =>
      apiClient.get<SavingsProposalsListResponse>('/savings/proposals', {
        budget_month_id: budgetMonthId!,
      }),
    enabled: !!budgetMonthId,
  });
}

export function useCreateSavingsRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: SavingsRuleCreateRequest) =>
      apiClient.post<SavingsRuleResponse>('/savings/rules', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'rules'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

export function useUpdateSavingsRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      ruleId,
      data,
    }: {
      ruleId: string;
      data: SavingsRuleUpdateRequest;
    }) => apiClient.put<SavingsRuleResponse>(`/savings/rules/${ruleId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'rules'] });
      queryClient.invalidateQueries({ queryKey: ['savings', 'proposals'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

export function useGenerateProposals() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (budgetMonthId: string) =>
      apiClient.post<SavingsProposalsListResponse>('/savings/proposals/generate', {
        budget_month_id: budgetMonthId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'proposals'] });
    },
  });
}

export function useApproveProposal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      proposalId,
      finalAmount,
    }: {
      proposalId: string;
      finalAmount?: number;
    }) =>
      apiClient.post<SavingsProposalResponse>(
        `/savings/proposals/${proposalId}/approve`,
        finalAmount !== undefined ? { final_amount: finalAmount } : {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'proposals'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useRejectProposal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (proposalId: string) =>
      apiClient.post<SavingsProposalResponse>(
        `/savings/proposals/${proposalId}/reject`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'proposals'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useCreateManualSavings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ManualSavingsCreateRequest) =>
      apiClient.post<ManualSavingsResponse>('/savings/manual', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['savings', 'proposals'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}
