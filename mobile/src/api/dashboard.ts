import { useQuery } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { DashboardSummary } from '@/types/api';

export function useDashboardSummary(year: number, month: number) {
  return useQuery({
    queryKey: ['dashboard', { year, month }],
    queryFn: () =>
      apiClient.get<DashboardSummary>('/dashboard/summary', {
        year: String(year),
        month: String(month),
      }),
  });
}
