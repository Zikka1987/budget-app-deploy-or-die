import { useInfiniteQuery } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  ReceiptSearchResponse,
  ReceiptStatus,
  TransactionSearchResponse,
  TransactionSource,
  TransactionType,
} from '@/types/api';

const PAGE_SIZE = 50;

export interface ReceiptSearchFilters {
  merchant?: string;
  category_id?: string;
  date_from?: string;
  date_to?: string;
  amount_min?: string;
  amount_max?: string;
  status?: ReceiptStatus;
}

export interface TransactionSearchFilters {
  category_id?: string;
  type?: TransactionType;
  source?: TransactionSource;
  date_from?: string;
  date_to?: string;
  amount_min?: string;
  amount_max?: string;
}

function stripFilters(
  filters: Record<string, string | undefined>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && String(v).trim() !== '') {
      out[k] = String(v).trim();
    }
  }
  return out;
}

export function useSearchReceipts(filters: ReceiptSearchFilters) {
  const stripped = stripFilters(filters as Record<string, string | undefined>);

  return useInfiniteQuery({
    queryKey: ['search', 'receipts', stripped],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      apiClient.get<ReceiptSearchResponse>('/search/receipts', {
        ...stripped,
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      }),
    getNextPageParam: (lastPage, allPages, lastPageParam) => {
      const loaded = allPages.reduce((n, p) => n + p.results.length, 0);
      if (loaded >= lastPage.total) return undefined;
      if (lastPage.results.length < PAGE_SIZE) return undefined;
      return (lastPageParam as number) + PAGE_SIZE;
    },
  });
}

export function useSearchTransactions(filters: TransactionSearchFilters) {
  const stripped = stripFilters(filters as Record<string, string | undefined>);

  return useInfiniteQuery({
    queryKey: ['search', 'transactions', stripped],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      apiClient.get<TransactionSearchResponse>('/search/transactions', {
        ...stripped,
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      }),
    getNextPageParam: (lastPage, allPages, lastPageParam) => {
      const loaded = allPages.reduce((n, p) => n + p.results.length, 0);
      if (loaded >= lastPage.total) return undefined;
      if (lastPage.results.length < PAGE_SIZE) return undefined;
      return (lastPageParam as number) + PAGE_SIZE;
    },
  });
}
