import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  HouseholdCreateRequest,
  HouseholdCreateResponse,
  HouseholdResponse,
} from '@/types/api';

export function useCreateHousehold() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: HouseholdCreateRequest) =>
      apiClient.post<HouseholdCreateResponse>('/households', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] });
    },
  });
}

export function useHousehold() {
  return useQuery({
    queryKey: ['household', 'me'],
    queryFn: () => apiClient.get<HouseholdResponse>('/households/me'),
  });
}
