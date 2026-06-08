import React, { useState } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { useCategories, useCreateCategory } from '@/api/categories';
import { useOnboardingStatus } from '@/api/onboarding';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import type { TransactionType, CategoryResponse } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

const CATEGORY_TYPES: { type: TransactionType; label: string }[] = [
  { type: 'income', label: 'Income' },
  { type: 'expense', label: 'Expense' },
  { type: 'savings', label: 'Savings' },
];

function CategorySection({ type, label }: { type: TransactionType; label: string }) {
  const { data: categories, isLoading } = useCategories(type);
  const createCategory = useCreateCategory();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');

  const handleAdd = () => {
    if (!name.trim()) return;
    createCategory.mutate(
      { type, name: name.trim() },
      {
        onSuccess: () => {
          setName('');
          setAdding(false);
        },
      },
    );
  };

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{label}</Text>

      {isLoading ? (
        <View style={styles.sectionLoading}>
          <LoadingSpinner />
        </View>
      ) : (
        <>
          {categories?.map((cat: CategoryResponse) => (
            <View key={cat.id} style={styles.categoryRow}>
              <Text style={styles.categoryName}>{cat.name}</Text>
            </View>
          ))}

          {categories?.length === 0 && !adding && (
            <Text style={styles.empty}>No {label.toLowerCase()} categories yet</Text>
          )}
        </>
      )}

      {adding ? (
        <View style={styles.addForm}>
          <TextInput
            label={`${label} category name`}
            placeholder={`e.g. ${type === 'income' ? 'Salary' : type === 'expense' ? 'Groceries' : 'General Savings'}`}
            value={name}
            onChangeText={setName}
            autoFocus
          />
          <View style={styles.addActions}>
            <Button
              title="Save"
              onPress={handleAdd}
              loading={createCategory.isPending}
              disabled={!name.trim()}
              style={styles.addButton}
            />
            <Button
              title="Cancel"
              onPress={() => { setAdding(false); setName(''); }}
              variant="ghost"
              style={styles.addButton}
            />
          </View>
        </View>
      ) : (
        <Pressable onPress={() => setAdding(true)} style={styles.addTrigger}>
          <Text style={styles.addTriggerText}>+ Add {label.toLowerCase()} category</Text>
        </Pressable>
      )}
    </View>
  );
}

export default function CategoriesScreen() {
  const { data: onboarding } = useOnboardingStatus();

  const allReady =
    onboarding?.has_income_category &&
    onboarding?.has_expense_category &&
    onboarding?.has_savings_category;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <FlatList
        data={CATEGORY_TYPES}
        keyExtractor={(item) => item.type}
        contentContainerStyle={styles.content}
        ListHeaderComponent={
          <View style={styles.header}>
            <Text style={styles.title}>Set Up Categories</Text>
            <Text style={styles.subtitle}>
              Create at least one category for each type
            </Text>
            <View style={styles.progress}>
              <ProgressCheck label="Income" done={!!onboarding?.has_income_category} />
              <ProgressCheck label="Expense" done={!!onboarding?.has_expense_category} />
              <ProgressCheck label="Savings" done={!!onboarding?.has_savings_category} />
            </View>
          </View>
        }
        renderItem={({ item }) => (
          <CategorySection type={item.type} label={item.label} />
        )}
        ListFooterComponent={
          <View style={styles.footer}>
            <Button
              title="Continue"
              onPress={() => router.replace('/(onboarding)/initialize-month')}
              disabled={!allReady}
            />
          </View>
        }
      />
    </KeyboardAvoidingView>
  );
}

function ProgressCheck({ label, done }: { label: string; done: boolean }) {
  return (
    <View style={styles.checkRow}>
      <Text style={[styles.checkIcon, done && styles.checkIconDone]}>
        {done ? '\u2713' : '\u25CB'}
      </Text>
      <Text style={[styles.checkLabel, done && styles.checkLabelDone]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    padding: spacing.xl,
    paddingTop: spacing.xxl + spacing.xxl,
  },
  header: {
    marginBottom: spacing.xl,
  },
  title: {
    fontSize: fontSize.xxl,
    fontWeight: fontWeight.bold,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  subtitle: {
    fontSize: fontSize.md,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  progress: {
    flexDirection: 'row',
    gap: spacing.lg,
  },
  checkRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  checkIcon: {
    fontSize: fontSize.md,
    color: colors.textTertiary,
  },
  checkIconDone: {
    color: colors.success,
  },
  checkLabel: {
    fontSize: fontSize.sm,
    color: colors.textTertiary,
  },
  checkLabelDone: {
    color: colors.success,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  sectionLoading: {
    height: 60,
  },
  categoryRow: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  categoryName: {
    fontSize: fontSize.md,
    color: colors.text,
  },
  empty: {
    fontSize: fontSize.sm,
    color: colors.textTertiary,
    paddingVertical: spacing.sm,
  },
  addForm: {
    marginTop: spacing.sm,
  },
  addActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  addButton: {
    flex: 1,
  },
  addTrigger: {
    paddingVertical: spacing.sm,
  },
  addTriggerText: {
    fontSize: fontSize.sm,
    color: colors.primary,
    fontWeight: fontWeight.medium,
  },
  footer: {
    marginTop: spacing.lg,
    paddingBottom: spacing.xxl,
  },
});
