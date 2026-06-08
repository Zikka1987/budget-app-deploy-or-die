import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  IncomeCreateRequest,
  IncomeResponse,
  IncomeUpdateRequest,
  IncomesListResponse,
} from '@/types/api';

export function useIncomes(budgetMonthId?: string) {
  return useQuery({
    queryKey: ['incomes', { budgetMonthId }],
    queryFn: () =>
      apiClient.get<IncomesListResponse>('/incomes/', {
        budget_month_id: budgetMonthId!,
      }),
    enabled: !!budgetMonthId,
  });
}

export function useCreateIncome() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: IncomeCreateRequest) =>
      apiClient.post<IncomeResponse>('/incomes/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incomes'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useUpdateIncome() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      transactionId,
      data,
    }: {
      transactionId: string;
      data: IncomeUpdateRequest;
    }) => apiClient.put<IncomeResponse>(`/incomes/${transactionId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incomes'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useDeleteIncome() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (transactionId: string) =>
      apiClient.del(`/incomes/${transactionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incomes'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}
