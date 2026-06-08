import React from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useBudgetMonths, useInitializeMonth } from '@/api/budgets';
import { useSelectedMonth } from '@/contexts/month-context';
import { Button } from '@/components/ui/Button';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { formatMonthYear } from '@/lib/format';
import type { BudgetMonthListItem } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function getCurrentMonthDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}-01`;
}

export default function BudgetMonthsScreen() {
  const { setMonth } = useSelectedMonth();
  const { data, isLoading, error, refetch } = useBudgetMonths();
  const initMonth = useInitializeMonth();

  const currentMonthDate = getCurrentMonthDate();
  const currentMonthExists = data?.months.some((m) => m.month === currentMonthDate);

  const handleSelect = (item: BudgetMonthListItem) => {
    const date = new Date(item.month);
    setMonth(date.getFullYear(), date.getMonth() + 1);
    router.back();
  };

  const handleInitialize = () => {
    initMonth.mutate({ month: currentMonthDate });
  };

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorView message="Could not load budget months." onRetry={() => refetch()} />;

  return (
    <View style={styles.container}>
      {!currentMonthExists && (
        <View style={styles.initSection}>
          <Button
            title="Initialize Current Month"
            onPress={handleInitialize}
            loading={initMonth.isPending}
          />
        </View>
      )}
      <FlatList
        data={data?.months ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => handleSelect(item)}>
            <Text style={styles.monthLabel}>{formatMonthYear(item.month)}</Text>
            {item.is_closed && (
              <View style={styles.closedBadge}>
                <Text style={styles.closedText}>Closed</Text>
              </View>
            )}
          </Pressable>
        )}
        ListEmptyComponent={
          <Text style={styles.empty}>No budget months yet.</Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  initSection: {
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  list: {
    padding: spacing.lg,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  monthLabel: {
    fontSize: fontSize.md,
    color: colors.text,
    fontWeight: fontWeight.medium,
    textTransform: 'capitalize',
  },
  closedBadge: {
    backgroundColor: colors.warningLight,
    paddingVertical: 2,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  closedText: {
    fontSize: fontSize.xs,
    color: colors.warning,
    fontWeight: fontWeight.medium,
  },
  empty: {
    fontSize: fontSize.sm,
    color: colors.textTertiary,
    textAlign: 'center',
    paddingVertical: spacing.xxl,
  },
});
