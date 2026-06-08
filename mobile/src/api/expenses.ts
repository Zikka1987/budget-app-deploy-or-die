import { useMutation, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ExpenseCreateRequest, ExpenseResponse } from '@/types/api';

export function useCreateExpense() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ExpenseCreateRequest) =>
      apiClient.post<ExpenseResponse>('/expenses/', data),
    onSuccess: () => {
      // Manual expenses appear in budget actuals, dashboard category
      // breakdowns, and search results. Mirror the manual-savings invalidation
      // set so all three surfaces refresh immediately. Receipts list is NOT
      // invalidated — manual expenses don't appear there (the receipts list
      // is specifically receipts, not all expense transactions).
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}
