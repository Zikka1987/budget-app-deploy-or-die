import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  CategoryCreateRequest,
  CategoryResponse,
  CategoryUpdateRequest,
  TransactionType,
} from '@/types/api';

export function useCategories(type?: TransactionType) {
  const params: Record<string, string> = {};
  if (type) params.type = type;

  return useQuery({
    queryKey: ['categories', { type }],
    queryFn: () => apiClient.get<CategoryResponse[]>('/categories/', params),
  });
}

export function useCreateCategory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CategoryCreateRequest) =>
      apiClient.post<CategoryResponse>('/categories/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['categories'] });
      queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] });
    },
  });
}

// Renaming a category leaves IDs intact but updates the displayed `category_name`
// that is denormalised into many cached responses (BudgetLine, IncomeResponse,
// ReceiptItem, SavingsRule, dashboard category breakdowns, transaction search
// results). Invalidate every cache that carries it so the new name surfaces
// immediately across the app without a manual refresh.
const RENAME_INVALIDATION_KEYS: ReadonlyArray<readonly unknown[]> = [
  ['categories'],
  ['budgets', 'month'],
  ['dashboard'],
  ['incomes'],
  ['savings', 'rules'],
  ['receipts'],
  ['receipt-review'],
  ['search'],
];

export function useUpdateCategory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      categoryId,
      data,
    }: {
      categoryId: string;
      data: CategoryUpdateRequest;
    }) => apiClient.put<CategoryResponse>(`/categories/${categoryId}`, data),
    onSuccess: () => {
      for (const key of RENAME_INVALIDATION_KEYS) {
        queryClient.invalidateQueries({ queryKey: key as unknown[] });
      }
    },
  });
}

export function useArchiveCategory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (categoryId: string) =>
      apiClient.post<CategoryResponse>(
        `/categories/${categoryId}/archive`,
        {},
      ),
    onSuccess: () => {
      // Same surface as rename — archived category disappears from pickers
      // (driven by `useCategories(type)`) but past rows still display its
      // historical name (history-preserving per CLAUDE.md). Plus
      // ['onboarding', 'status'] defensively in case the household drops
      // to zero of a type through a parallel channel; the UI guard prevents
      // this happening through the categories screen itself.
      for (const key of RENAME_INVALIDATION_KEYS) {
        queryClient.invalidateQueries({ queryKey: key as unknown[] });
      }
      queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] });
    },
  });
}

