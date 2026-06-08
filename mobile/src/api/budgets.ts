import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  BudgetLineResponse,
  BudgetLineUpdateRequest,
  BudgetMonthInitializeRequest,
  BudgetMonthResponse,
  BudgetMonthsListResponse,
} from '@/types/api';

export function useBudgetMonths() {
  return useQuery({
    queryKey: ['budgets', 'months'],
    queryFn: () => apiClient.get<BudgetMonthsListResponse>('/budgets/months'),
  });
}

export function useBudgetMonth(monthId?: string) {
  return useQuery({
    queryKey: ['budgets', 'month', monthId],
    queryFn: () => apiClient.get<BudgetMonthResponse>(`/budgets/months/${monthId}`),
    enabled: !!monthId,
  });
}

export function useInitializeMonth() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: BudgetMonthInitializeRequest) =>
      apiClient.post<BudgetMonthResponse>('/budgets/months/initialize', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets', 'months'] });
    },
  });
}

export function useUpsertBudgetLine() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      monthId,
      categoryId,
      data,
    }: {
      monthId: string;
      categoryId: string;
      data: BudgetLineUpdateRequest;
    }) =>
      apiClient.put<BudgetLineResponse>(
        `/budgets/months/${monthId}/lines/${categoryId}`,
        data,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
