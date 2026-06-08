import React from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useBudgetMonths } from '@/api/budgets';
import { useDeleteIncome, useIncomes } from '@/api/incomes';
import { useSelectedMonth } from '@/contexts/month-context';
import { MonthSelector } from '@/components/MonthSelector';
import { Button } from '@/components/ui/Button';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatDKK, formatDate } from '@/lib/format';
import type { IncomeResponse } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function IncomeListScreen() {
  const { year, month } = useSelectedMonth();
  const monthStr = `${year}-${String(month).padStart(2, '0')}-01`;

  const { data: monthsData, isLoading: monthsLoading } = useBudgetMonths();
  const budgetMonth = monthsData?.months.find((m) => m.month === monthStr);
  const budgetMonthId = budgetMonth?.id;

  const { data, isLoading, error } = useIncomes(budgetMonthId);
  const deleteIncome = useDeleteIncome();

  const handleDelete = (item: IncomeResponse) => {
    Alert.alert(
      'Delete Income',
      `Delete "${item.category_name}" entry of ${formatDKK(item.amount)}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () =>
            deleteIncome.mutate(item.id, {
              onError: (err) => Alert.alert('Error', err.message),
            }),
        },
      ],
    );
  };

  const handleEdit = (item: IncomeResponse) => {
    router.push({
      pathname: '/(main)/income/form',
      params: { transactionId: item.id, budgetMonthId },
    });
  };

  const handleAdd = () => {
    router.push({
      pathname: '/(main)/income/form',
      params: { budgetMonthId },
    });
  };

  if (monthsLoading) return <LoadingSpinner />;

  if (!budgetMonthId) {
    return (
      <View style={styles.emptyContainer}>
        <MonthSelector />
        <EmptyState message="No budget month for this period. Initialize it from the Budget tab." />
      </View>
    );
  }

  if (isLoading) return <LoadingSpinner />;

  return (
    <View style={styles.container}>
      <FlatList
        data={data?.incomes ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View>
            <MonthSelector />
            <Button title="Add Income" onPress={handleAdd} style={styles.addButton} />
          </View>
        }
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => handleEdit(item)}>
            <View style={styles.rowLeft}>
              <Text style={styles.categoryName} numberOfLines={1}>
                {item.category_name}
              </Text>
              <Text style={styles.rowDate}>{formatDate(item.transaction_date)}</Text>
              {item.description ? (
                <Text style={styles.rowDescription} numberOfLines={1}>
                  {item.description}
                </Text>
              ) : null}
            </View>
            <View style={styles.rowRight}>
              <Text style={styles.amount}>{formatDKK(item.amount)}</Text>
              <Pressable
                onPress={() => handleDelete(item)}
                hitSlop={8}
                style={styles.deleteButton}
              >
                <Text style={styles.deleteText}>Delete</Text>
              </Pressable>
            </View>
          </Pressable>
        )}
        ListEmptyComponent={
          <EmptyState message="No income entries yet." />
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
  emptyContainer: {
    flex: 1,
    backgroundColor: colors.surface,
    padding: spacing.lg,
    paddingTop: spacing.xxl,
  },
  list: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  addButton: {
    marginBottom: spacing.lg,
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
  categoryName: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
  },
  rowDate: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginTop: 2,
  },
  rowDescription: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
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
  },
  deleteButton: {
    marginTop: spacing.xs,
  },
  deleteText: {
    fontSize: fontSize.xs,
    color: colors.danger,
  },
});
