import React from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useReceipts } from '@/api/receipts';
import { Button } from '@/components/ui/Button';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatDKK, formatDate } from '@/lib/format';
import type { ReceiptListItem, ReceiptStatus } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

const statusConfig: Record<ReceiptStatus, { label: string; bg: string; fg: string }> = {
  uploaded: { label: 'Uploaded', bg: colors.borderLight, fg: colors.textSecondary },
  processing: { label: 'Processing', bg: colors.primaryLight, fg: colors.primary },
  ocr_complete: { label: 'Ready for review', bg: colors.warningLight, fg: colors.warning },
  reviewed: { label: 'Reviewed', bg: colors.successLight, fg: colors.success },
  posted: { label: 'Posted', bg: colors.successLight, fg: colors.success },
  failed: { label: 'Failed', bg: colors.dangerLight, fg: colors.danger },
};

export default function ReceiptListScreen() {
  const { data, isLoading, error, refetch } = useReceipts();

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorView message="Could not load receipts." onRetry={() => refetch()} />;

  return (
    <View style={styles.container}>
      <FlatList
        data={data ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.headerActions}>
            <Button
              title="Upload Receipt"
              onPress={() => router.push('/(main)/receipts/upload')}
            />
            <Button
              title="+ Manual entry"
              onPress={() => router.push('/(main)/receipts/manual')}
              variant="ghost"
              style={styles.manualButton}
            />
          </View>
        }
        renderItem={({ item }) => <ReceiptRow item={item} />}
        ListEmptyComponent={<EmptyState message="No receipts yet." />}
        onRefresh={refetch}
        refreshing={false}
      />
    </View>
  );
}

function ReceiptRow({ item }: { item: ReceiptListItem }) {
  const config = statusConfig[item.status];
  const displayName = item.store_name || item.file_name || 'Receipt';

  return (
    <Pressable
      style={styles.row}
      onPress={() => router.push({ pathname: '/(main)/receipts/[id]', params: { id: item.id } })}
    >
      <View style={styles.rowLeft}>
        <Text style={styles.storeName} numberOfLines={1}>
          {displayName}
        </Text>
        {item.receipt_date && (
          <Text style={styles.rowDate}>{formatDate(item.receipt_date)}</Text>
        )}
      </View>
      <View style={styles.rowRight}>
        {item.total_amount != null && (
          <Text style={styles.amount}>{formatDKK(item.total_amount)}</Text>
        )}
        <View style={[styles.statusBadge, { backgroundColor: config.bg }]}>
          <Text style={[styles.statusText, { color: config.fg }]}>{config.label}</Text>
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  list: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  headerActions: {
    marginBottom: spacing.lg,
  },
  manualButton: {
    marginTop: spacing.xs,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  rowLeft: {
    flex: 1,
    marginRight: spacing.md,
  },
  storeName: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
  },
  rowDate: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginTop: 2,
  },
  rowRight: {
    alignItems: 'flex-end',
  },
  amount: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    fontVariant: ['tabular-nums'],
    marginBottom: spacing.xs,
  },
  statusBadge: {
    paddingVertical: 2,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  statusText: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
  },
});
