import React, { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';

import { useCategories } from '@/api/categories';
import { useCreateIncome, useUpdateIncome } from '@/api/incomes';
import { useSelectedMonth } from '@/contexts/month-context';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { ErrorView } from '@/components/ui/ErrorView';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import type { CategoryResponse, IncomeResponse, IncomesListResponse } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function IncomeFormScreen() {
  const params = useLocalSearchParams<{ transactionId?: string; budgetMonthId?: string }>();
  const { transactionId, budgetMonthId } = params;
  const isEdit = !!transactionId;

  const { year, month } = useSelectedMonth();
  const queryClient = useQueryClient();
  const { data: incomeCategories } = useCategories('income');
  const createIncome = useCreateIncome();
  const updateIncome = useUpdateIncome();

  const [categoryId, setCategoryId] = useState('');
  const [amount, setAmount] = useState('');
  const [transactionDate, setTransactionDate] = useState(todayStr());
  const [description, setDescription] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const trimmedAmount = typeof amount === 'string' ? amount.trim() : '';

  // Load existing income from cache for edit mode
  useEffect(() => {
    if (!isEdit || loaded) return;
    if (!budgetMonthId) {
      setLoadError(true);
      return;
    }
    const cached = queryClient.getQueryData<IncomesListResponse>([
      'incomes',
      { budgetMonthId },
    ]);
    const existing = cached?.incomes.find((i) => i.id === transactionId);
    if (!existing) {
      setLoadError(true);
      return;
    }
    setCategoryId(existing.category_id);
    setAmount(
      typeof existing.amount === 'string'
        ? existing.amount
        : existing.amount != null
          ? String(existing.amount)
          : '',
    );
    setTransactionDate(existing.transaction_date);
    setDescription(existing.description ?? '');
    setLoaded(true);
  }, [isEdit, loaded, transactionId, budgetMonthId, queryClient]);

  if (isEdit && loadError) {
    return <ErrorView message="Could not load income entry. Go back and try again." />;
  }

  const handleSubmit = () => {
    if (!categoryId || !trimmedAmount) {
      Alert.alert('Validation', 'Category and amount are required.');
      return;
    }

    const onSuccess = (data: IncomeResponse) => {
      // Compare YYYY-MM only. Guard against `data.budget_month` being absent
      // or non-date (the update response currently omits the field), which
      // would otherwise trigger a false-positive alert with "Invalid Date".
      const selectedYM = `${year}-${String(month).padStart(2, '0')}`;
      const dataYM =
        typeof data.budget_month === 'string' ? data.budget_month.slice(0, 7) : '';
      const isShifted = /^\d{4}-\d{2}$/.test(dataYM) && dataYM !== selectedYM;
      if (isShifted) {
        const [yy, mm] = dataYM.split('-').map(Number);
        const label = new Date(yy, mm - 1, 1).toLocaleDateString('da-DK', {
          year: 'numeric',
          month: 'long',
        });
        Alert.alert(
          'Late-Income Shift',
          `Income was assigned to ${label} (late-income shift).`,
          [{ text: 'OK', onPress: () => router.back() }],
        );
        return;
      }
      router.back();
    };

    const onError = (err: Error) => {
      Alert.alert('Error', err.message);
    };

    if (isEdit && transactionId) {
      updateIncome.mutate(
        {
          transactionId,
          data: {
            category_id: categoryId,
            amount: trimmedAmount,
            transaction_date: transactionDate,
            description: description.trim() || null,
          },
        },
        { onSuccess, onError },
      );
    } else {
      createIncome.mutate(
        {
          category_id: categoryId,
          amount: trimmedAmount,
          transaction_date: transactionDate,
          description: description.trim() || null,
        },
        { onSuccess, onError },
      );
    }
  };

  const isPending = createIncome.isPending || updateIncome.isPending;

  return (
    <KeyboardAwareScreen
      backgroundColor={colors.surface}
      contentContainerStyle={styles.content}
    >
      <Text style={styles.sectionLabel}>Category</Text>
      <View style={styles.categoryList}>
        {incomeCategories
          ?.filter((c: CategoryResponse) => !c.archived_at)
          .map((cat: CategoryResponse) => (
            <Pressable
              key={cat.id}
              style={[
                styles.categoryChip,
                categoryId === cat.id && styles.categoryChipSelected,
              ]}
              onPress={() => setCategoryId(cat.id)}
            >
              <Text
                style={[
                  styles.categoryChipText,
                  categoryId === cat.id && styles.categoryChipTextSelected,
                ]}
              >
                {cat.name}
              </Text>
            </Pressable>
          ))}
      </View>

      <TextInput
        label="Amount"
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        placeholder="0.00"
      />

      <TextInput
        label="Transaction date (YYYY-MM-DD)"
        value={transactionDate}
        onChangeText={setTransactionDate}
        placeholder={todayStr()}
      />

      <TextInput
        label="Description (optional)"
        value={description}
        onChangeText={setDescription}
        placeholder="e.g. April salary"
      />

      <Button
        title={isEdit ? 'Update Income' : 'Add Income'}
        onPress={handleSubmit}
        loading={isPending}
        disabled={!categoryId || !trimmedAmount}
      />
    </KeyboardAwareScreen>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: spacing.xl,
  },
  sectionLabel: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  categoryList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  categoryChip: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
  },
  categoryChipSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primaryLight,
  },
  categoryChipText: {
    fontSize: fontSize.sm,
    color: colors.text,
  },
  categoryChipTextSelected: {
    color: colors.primary,
    fontWeight: fontWeight.semibold,
  },
});
