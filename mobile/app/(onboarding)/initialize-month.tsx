import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useBudgetMonths, useInitializeMonth } from '@/api/budgets';
import { Button } from '@/components/ui/Button';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function getCurrentMonthDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}-01`;
}

function formatMonthLabel(): string {
  return new Date().toLocaleDateString('da-DK', {
    year: 'numeric',
    month: 'long',
  });
}

export default function InitializeMonthScreen() {
  const { data: monthsData, isLoading } = useBudgetMonths();
  const initMonth = useInitializeMonth();
  const currentMonthDate = getCurrentMonthDate();

  const alreadyExists = monthsData?.months.some(
    (m) => m.month === currentMonthDate,
  );

  if (isLoading) return <LoadingSpinner />;

  if (alreadyExists) {
    router.replace('/(main)');
    return null;
  }

  const handleInitialize = () => {
    initMonth.mutate(
      { month: currentMonthDate },
      { onSuccess: () => router.replace('/(main)') },
    );
  };

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Start Your First Month</Text>
        <Text style={styles.subtitle}>
          Create a budget month for {formatMonthLabel()}
        </Text>

        {initMonth.error && (
          <Text style={styles.error}>
            {(initMonth.error as any).message ?? 'Failed to create budget month'}
          </Text>
        )}

        <Button
          title="Create Budget Month"
          onPress={handleInitialize}
          loading={initMonth.isPending}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.xl,
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
    marginBottom: spacing.xxl,
  },
  error: {
    color: colors.danger,
    fontSize: fontSize.sm,
    marginBottom: spacing.lg,
    textAlign: 'center',
  },
});
