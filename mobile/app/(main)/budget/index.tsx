import React, { useMemo, useState } from 'react';
import {
  Alert,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { useBudgetMonth, useBudgetMonths, useInitializeMonth, useUpsertBudgetLine } from '@/api/budgets';
import { useCategories } from '@/api/categories';
import { useSelectedMonth } from '@/contexts/month-context';
import { MonthSelector } from '@/components/MonthSelector';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatDKK } from '@/lib/format';
import type { BudgetLineResponse, CategoryResponse, TransactionType } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

interface MergedLine {
  categoryId: string;
  categoryName: string;
  categoryType: TransactionType;
  plannedAmount: string;
  actualAmount: string;
  notes: string | null;
  hasLine: boolean;
}

export default function BudgetDetailScreen() {
  const { year, month } = useSelectedMonth();
  const monthStr = `${year}-${String(month).padStart(2, '0')}-01`;

  const { data: monthsData, isLoading: monthsLoading } = useBudgetMonths();
  const budgetMonth = monthsData?.months.find((m) => m.month === monthStr);
  const monthId = budgetMonth?.id;

  const { data: detail, isLoading: detailLoading, error: detailError } = useBudgetMonth(monthId);
  const { data: incomeCategories } = useCategories('income');
  const { data: expenseCategories } = useCategories('expense');
  const { data: savingsCategories } = useCategories('savings');

  const initMonth = useInitializeMonth();
  const upsertLine = useUpsertBudgetLine();

  const [editingLine, setEditingLine] = useState<MergedLine | null>(null);
  const [editAmount, setEditAmount] = useState('');
  const [editNotes, setEditNotes] = useState('');

  const mergedSections = useMemo(() => {
    if (!detail) return null;

    const merge = (
      categories: CategoryResponse[] | undefined,
      type: TransactionType,
    ): MergedLine[] => {
      if (!categories) return [];
      return categories
        .filter((c) => !c.archived_at)
        .map((cat) => {
          const line = detail.lines.find((l) => l.category_id === cat.id);
          return {
            categoryId: cat.id,
            categoryName: cat.name,
            categoryType: type,
            plannedAmount: line?.planned_amount ?? '0.00',
            actualAmount: line?.actual_amount ?? '0.00',
            notes: line?.notes ?? null,
            hasLine: !!line,
          };
        });
    };

    return {
      income: merge(incomeCategories, 'income'),
      expense: merge(expenseCategories, 'expense'),
      savings: merge(savingsCategories, 'savings'),
    };
  }, [detail, incomeCategories, expenseCategories, savingsCategories]);

  const openEdit = (line: MergedLine) => {
    if (detail?.is_closed) return;
    setEditingLine(line);
    setEditAmount(line.plannedAmount === '0.00' && !line.hasLine ? '' : line.plannedAmount);
    setEditNotes(line.notes ?? '');
  };

  const handleSave = () => {
    if (!monthId || !editingLine) return;
    const amount = editAmount.trim() || '0.00';
    upsertLine.mutate(
      {
        monthId,
        categoryId: editingLine.categoryId,
        data: {
          planned_amount: amount,
          notes: editNotes.trim() || null,
        },
      },
      {
        onSuccess: () => setEditingLine(null),
        onError: (err) => Alert.alert('Error', err.message),
      },
    );
  };

  const handleInitialize = () => {
    initMonth.mutate(
      { month: monthStr },
      {
        onError: (err) => Alert.alert('Error', err.message),
      },
    );
  };

  if (monthsLoading) return <LoadingSpinner />;

  if (!monthId) {
    return (
      <View style={styles.emptyContainer}>
        <MonthSelector onMonthLabelPress={() => router.push('/(main)/budget/months')} />
        <EmptyState message={`No budget month for ${monthStr}. Initialize it to start budgeting.`} />
        <View style={styles.initButton}>
          <Button
            title="Initialize Month"
            onPress={handleInitialize}
            loading={initMonth.isPending}
          />
        </View>
      </View>
    );
  }

  if (detailLoading) return <LoadingSpinner />;
  if (detailError) {
    return <ErrorView message="Could not load budget details." onRetry={() => {}} />;
  }
  if (!mergedSections) return <LoadingSpinner />;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <MonthSelector onMonthLabelPress={() => router.push('/(main)/budget/months')} />

      {detail?.is_closed && (
        <View style={styles.closedBadge}>
          <Text style={styles.closedText}>This month is closed (read-only)</Text>
        </View>
      )}

      <BudgetSection title="Income" lines={mergedSections.income} onEdit={openEdit} readOnly={!!detail?.is_closed} />
      <BudgetSection title="Expenses" lines={mergedSections.expense} onEdit={openEdit} readOnly={!!detail?.is_closed} />
      <BudgetSection title="Savings" lines={mergedSections.savings} onEdit={openEdit} readOnly={!!detail?.is_closed} />

      <Modal visible={!!editingLine} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>{editingLine?.categoryName}</Text>
            <TextInput
              label="Planned amount"
              value={editAmount}
              onChangeText={setEditAmount}
              keyboardType="numeric"
              autoFocus
            />
            <TextInput
              label="Notes (optional)"
              value={editNotes}
              onChangeText={setEditNotes}
            />
            <View style={styles.modalActions}>
              <Button
                title="Save"
                onPress={handleSave}
                loading={upsertLine.isPending}
                style={styles.modalButton}
              />
              <Button
                title="Cancel"
                onPress={() => setEditingLine(null)}
                variant="ghost"
                style={styles.modalButton}
              />
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function BudgetSection({
  title,
  lines,
  onEdit,
  readOnly,
}: {
  title: string;
  lines: MergedLine[];
  onEdit: (line: MergedLine) => void;
  readOnly: boolean;
}) {
  if (lines.length === 0) return null;

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {lines.map((line) => (
        <Pressable
          key={line.categoryId}
          style={styles.lineRow}
          onPress={() => onEdit(line)}
          disabled={readOnly}
        >
          <Text style={styles.lineName} numberOfLines={1}>
            {line.categoryName}
          </Text>
          <View style={styles.lineAmounts}>
            <Text style={styles.linePlanned}>{formatDKK(line.plannedAmount)}</Text>
            <Text style={styles.lineActual}>/ {formatDKK(line.actualAmount)}</Text>
          </View>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  emptyContainer: {
    flex: 1,
    backgroundColor: colors.surface,
    padding: spacing.lg,
    paddingTop: spacing.xxl,
  },
  initButton: {
    marginTop: spacing.lg,
    paddingHorizontal: spacing.xl,
  },
  closedBadge: {
    backgroundColor: colors.warningLight,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.lg,
    alignItems: 'center',
  },
  closedText: {
    fontSize: fontSize.sm,
    color: colors.warning,
    fontWeight: fontWeight.medium,
  },
  section: {
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  lineRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  lineName: {
    fontSize: fontSize.sm,
    color: colors.text,
    flex: 1,
    marginRight: spacing.sm,
  },
  lineAmounts: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  linePlanned: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    fontVariant: ['tabular-nums'],
  },
  lineActual: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginLeft: 4,
    fontVariant: ['tabular-nums'],
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  modalContent: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    padding: spacing.xl,
  },
  modalTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.lg,
  },
  modalActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  modalButton: {
    flex: 1,
  },
});
