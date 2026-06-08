import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type {
  InviteAcceptRequest,
  InviteAcceptResponse,
  InviteCreateRequest,
  InviteCreateResponse,
  InviteListResponse,
  InviteLookupRequest,
  InviteLookupResponse,
  InviteStatus,
} from '@/types/api';

export function useInvites(status?: InviteStatus) {
  return useQuery({
    queryKey: ['invites', { status }],
    queryFn: () =>
      apiClient.get<InviteListResponse>(
        '/invites',
        status ? { status } : undefined,
      ),
  });
}

export function useCreateInvite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: InviteCreateRequest) =>
      apiClient.post<InviteCreateResponse>('/invites', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invites'] });
    },
  });
}

export function useRevokeInvite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (inviteId: string) => apiClient.del(`/invites/${inviteId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invites'] });
    },
  });
}

export function useLookupInvite() {
  return useMutation({
    mutationFn: (data: InviteLookupRequest) =>
      apiClient.post<InviteLookupResponse>('/invites/lookup', data),
  });
}

export function useAcceptInvite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: InviteAcceptRequest) =>
      apiClient.post<InviteAcceptResponse>('/invites/accept', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] });
      queryClient.invalidateQueries({ queryKey: ['household', 'me'] });
      queryClient.invalidateQueries({ queryKey: ['invites'] });
    },
  });
}
