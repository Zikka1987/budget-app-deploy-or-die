import React, { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useCategories } from '@/api/categories';
import { useCreateManualSavings } from '@/api/savings';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import type { CategoryResponse } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function ManualSavingsScreen() {
  const { data: savingsCategories } = useCategories('savings');
  const createManual = useCreateManualSavings();

  const [categoryId, setCategoryId] = useState('');
  const [amount, setAmount] = useState('');
  const [transactionDate, setTransactionDate] = useState(todayStr());
  const [description, setDescription] = useState('');

  const handleSubmit = () => {
    if (!categoryId) {
      Alert.alert('Validation', 'Category is required.');
      return;
    }
    const parsed = parseFloat(amount.trim());
    if (isNaN(parsed) || parsed <= 0) {
      Alert.alert('Validation', 'Amount must be a positive number.');
      return;
    }

    createManual.mutate(
      {
        category_id: categoryId,
        amount: parsed,
        transaction_date: transactionDate,
        description: description.trim() || null,
      },
      {
        onSuccess: () => router.back(),
        onError: (err) => Alert.alert('Error', err.message),
      },
    );
  };

  return (
    <KeyboardAwareScreen
      backgroundColor={colors.surface}
      contentContainerStyle={styles.content}
    >
      <Text style={styles.sectionLabel}>Category</Text>
      <View style={styles.categoryList}>
        {savingsCategories
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
        placeholder="e.g. Extra savings deposit"
      />

      <Button
        title="Add Manual Savings"
        onPress={handleSubmit}
        loading={createManual.isPending}
        disabled={!categoryId || !amount.trim()}
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
