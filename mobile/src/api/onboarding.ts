import { useQuery } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { OnboardingStatus } from '@/types/api';

export function useOnboardingStatus(enabled: boolean = true) {
  return useQuery({
    queryKey: ['onboarding', 'status'],
    queryFn: () => apiClient.get<OnboardingStatus>('/onboarding/status'),
    enabled,
  });
}
