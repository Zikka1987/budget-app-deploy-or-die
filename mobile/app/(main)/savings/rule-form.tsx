import React, { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';

import { useCategories } from '@/api/categories';
import { useCreateSavingsRule, useUpdateSavingsRule } from '@/api/savings';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { ErrorView } from '@/components/ui/ErrorView';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import type {
  CategoryResponse,
  SavingsRuleResponse,
  SavingsRuleType,
  SavingsRulesListResponse,
} from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function RuleFormScreen() {
  const params = useLocalSearchParams<{ ruleId?: string }>();
  const { ruleId } = params;
  const isEdit = !!ruleId;

  const queryClient = useQueryClient();
  const { data: savingsCategories } = useCategories('savings');
  const createRule = useCreateSavingsRule();
  const updateRule = useUpdateSavingsRule();

  const [categoryId, setCategoryId] = useState('');
  const [ruleType, setRuleType] = useState<SavingsRuleType>('percent_of_income');
  const [label, setLabel] = useState('');
  const [percentValue, setPercentValue] = useState('');
  const [fixedAmount, setFixedAmount] = useState('');
  const [existingRule, setExistingRule] = useState<SavingsRuleResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!isEdit || loaded) return;
    const cached = queryClient.getQueryData<SavingsRulesListResponse>([
      'savings',
      'rules',
    ]);
    const existing = cached?.rules.find((r) => r.id === ruleId);
    if (!existing) {
      setLoadError(true);
      return;
    }
    setCategoryId(existing.category_id);
    setRuleType(existing.rule_type);
    setLabel(existing.label);
    setPercentValue(existing.percent_value !== null ? String(existing.percent_value) : '');
    setFixedAmount(existing.fixed_amount !== null ? String(existing.fixed_amount) : '');
    setExistingRule(existing);
    setLoaded(true);
  }, [isEdit, loaded, ruleId, queryClient]);

  if (isEdit && loadError) {
    return <ErrorView message="Could not load savings rule. Go back and try again." />;
  }

  const handleSubmit = () => {
    if (!isEdit && !categoryId) {
      Alert.alert('Validation', 'Category is required.');
      return;
    }
    if (!label.trim()) {
      Alert.alert('Validation', 'Label is required.');
      return;
    }

    if (ruleType === 'percent_of_income') {
      const v = parseFloat(percentValue.trim());
      if (isNaN(v) || v <= 0) {
        Alert.alert('Validation', 'Percent value must be a positive number.');
        return;
      }
    } else {
      const v = parseFloat(fixedAmount.trim());
      if (isNaN(v) || v <= 0) {
        Alert.alert('Validation', 'Fixed amount must be a positive number.');
        return;
      }
    }

    const onSuccess = () => router.back();
    const onError = (err: Error) => Alert.alert('Error', err.message);

    if (isEdit && ruleId) {
      updateRule.mutate(
        {
          ruleId,
          data: {
            label: label.trim(),
            percent_value:
              ruleType === 'percent_of_income' ? parseFloat(percentValue.trim()) : null,
            fixed_amount:
              ruleType === 'fixed_monthly' ? parseFloat(fixedAmount.trim()) : null,
          },
        },
        { onSuccess, onError },
      );
    } else {
      createRule.mutate(
        {
          category_id: categoryId,
          rule_type: ruleType,
          label: label.trim(),
          percent_value:
            ruleType === 'percent_of_income' ? parseFloat(percentValue.trim()) : null,
          fixed_amount:
            ruleType === 'fixed_monthly' ? parseFloat(fixedAmount.trim()) : null,
        },
        { onSuccess, onError },
      );
    }
  };

  const isPending = createRule.isPending || updateRule.isPending;

  return (
    <KeyboardAwareScreen
      backgroundColor={colors.surface}
      contentContainerStyle={styles.content}
    >
      <Text style={styles.sectionLabel}>Category</Text>
      {isEdit ? (
        <Text style={styles.readOnlyValue}>
          {existingRule?.category_name ?? '—'}
        </Text>
      ) : (
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
      )}

      <Text style={styles.sectionLabel}>Rule Type</Text>
      {isEdit ? (
        <Text style={styles.readOnlyValue}>
          {ruleType === 'percent_of_income' ? '% of Income' : 'Fixed Monthly'}
        </Text>
      ) : (
        <View style={styles.segmentRow}>
          <Pressable
            style={[
              styles.segmentPill,
              ruleType === 'percent_of_income' && styles.segmentPillActive,
            ]}
            onPress={() => setRuleType('percent_of_income')}
          >
            <Text
              style={[
                styles.segmentText,
                ruleType === 'percent_of_income' && styles.segmentTextActive,
              ]}
            >
              % of Income
            </Text>
          </Pressable>
          <Pressable
            style={[
              styles.segmentPill,
              ruleType === 'fixed_monthly' && styles.segmentPillActive,
            ]}
            onPress={() => setRuleType('fixed_monthly')}
          >
            <Text
              style={[
                styles.segmentText,
                ruleType === 'fixed_monthly' && styles.segmentTextActive,
              ]}
            >
              Fixed Monthly
            </Text>
          </Pressable>
        </View>
      )}

      <TextInput
        label="Label"
        value={label}
        onChangeText={setLabel}
        placeholder="e.g. Emergency fund 10%"
      />

      {ruleType === 'percent_of_income' ? (
        <TextInput
          label="Percent of income (%)"
          value={percentValue}
          onChangeText={setPercentValue}
          keyboardType="decimal-pad"
          placeholder="10.00"
        />
      ) : (
        <TextInput
          label="Fixed amount (kr.)"
          value={fixedAmount}
          onChangeText={setFixedAmount}
          keyboardType="decimal-pad"
          placeholder="500.00"
        />
      )}

      <Button
        title={isEdit ? 'Update Rule' : 'Add Rule'}
        onPress={handleSubmit}
        loading={isPending}
        disabled={!label.trim() || (!isEdit && !categoryId)}
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
  readOnlyValue: {
    fontSize: fontSize.md,
    color: colors.text,
    paddingVertical: spacing.sm,
    marginBottom: spacing.lg,
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
  segmentRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  segmentPill: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    alignItems: 'center',
  },
  segmentPillActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  segmentText: {
    fontSize: fontSize.sm,
    color: colors.text,
  },
  segmentTextActive: {
    color: colors.textInverse,
    fontWeight: fontWeight.semibold,
  },
});
