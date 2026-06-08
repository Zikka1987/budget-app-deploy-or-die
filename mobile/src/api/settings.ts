import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  HouseholdSettingsResponse,
  HouseholdSettingsUpdate,
} from '@/types/api';

export function useHouseholdSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () =>
      apiClient.get<HouseholdSettingsResponse>('/household-settings'),
  });
}

export function useUpdateHouseholdSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: HouseholdSettingsUpdate) =>
      apiClient.put<HouseholdSettingsResponse>('/household-settings', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
