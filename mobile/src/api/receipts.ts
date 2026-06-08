import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, LONG_REQUEST_TIMEOUT_MS } from '@/lib/api-client';
import type {
  ReceiptConfirmRequest,
  ReceiptConfirmResponse,
  ReceiptItemResponse,
  ReceiptItemUpdateRequest,
  ReceiptListItem,
  ReceiptResponse,
} from '@/types/api';

export function useReceipts() {
  return useQuery({
    queryKey: ['receipts'],
    queryFn: () => apiClient.get<ReceiptListItem[]>('/receipts/'),
  });
}

export function useReceipt(receiptId?: string) {
  return useQuery({
    queryKey: ['receipts', receiptId],
    queryFn: () =>
      apiClient.get<ReceiptResponse>(`/receipts/${receiptId}`),
    enabled: !!receiptId,
    refetchInterval: (query) =>
      query.state.data?.status === 'processing' ? 3000 : false,
  });
}

export function useReviewPayload(receiptId?: string, enabled = false) {
  return useQuery({
    queryKey: ['receipt-review', receiptId],
    queryFn: () =>
      apiClient.get<ReceiptResponse>(
        `/receipt-review/${receiptId}/payload`,
      ),
    enabled: !!receiptId && enabled,
  });
}

export function useUploadReceipt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (formData: FormData) =>
      apiClient.upload<ReceiptResponse>('/receipts/upload', formData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['receipts'] });
    },
  });
}

export function useParseReceipt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (receiptId: string) =>
      apiClient.post<ReceiptResponse>(
        `/receipts/${receiptId}/parse`,
        undefined,
        { timeoutMs: LONG_REQUEST_TIMEOUT_MS },
      ),
    onSuccess: (_data, receiptId) => {
      queryClient.invalidateQueries({ queryKey: ['receipts', receiptId] });
    },
  });
}

export function useCategorizeReceipt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (receiptId: string) =>
      apiClient.post<ReceiptResponse>(
        `/receipts/${receiptId}/categorize`,
        undefined,
        { timeoutMs: LONG_REQUEST_TIMEOUT_MS },
      ),
    onSuccess: (_data, receiptId) => {
      queryClient.invalidateQueries({ queryKey: ['receipts', receiptId] });
      queryClient.invalidateQueries({
        queryKey: ['receipt-review', receiptId],
      });
    },
  });
}

export function useUpdateReceiptItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      receiptId,
      itemId,
      data,
    }: {
      receiptId: string;
      itemId: string;
      data: ReceiptItemUpdateRequest;
    }) =>
      apiClient.put<ReceiptItemResponse>(
        `/receipt-review/${receiptId}/items/${itemId}`,
        data,
      ),
    onSuccess: (_data, { receiptId }) => {
      queryClient.invalidateQueries({
        queryKey: ['receipt-review', receiptId],
      });
    },
  });
}

export function useConfirmReceipt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      receiptId,
      data,
    }: {
      receiptId: string;
      data?: ReceiptConfirmRequest;
    }) =>
      apiClient.post<ReceiptConfirmResponse>(
        `/receipt-review/${receiptId}/confirm`,
        data,
      ),
    onSuccess: (_data, { receiptId }) => {
      queryClient.invalidateQueries({ queryKey: ['receipts'] });
      queryClient.invalidateQueries({ queryKey: ['receipts', receiptId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['budgets', 'month'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
    },
  });
}
