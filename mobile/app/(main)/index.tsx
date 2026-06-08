import React, { useCallback } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import { useDashboardSummary } from '@/api/dashboard';
import { useAuth } from '@/contexts/auth-context';
import { useSelectedMonth } from '@/contexts/month-context';
import { MonthSelector } from '@/components/MonthSelector';
import { Card } from '@/components/ui/Card';
import { AmountDisplay } from '@/components/ui/AmountDisplay';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import type { CategoryBudgetActual } from '@/types/api';
import { formatDKK } from '@/lib/format';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function DashboardScreen() {
  const { signOut } = useAuth();
  const { year, month } = useSelectedMonth();
  const queryClient = useQueryClient();
  const { data, isLoading, isRefetching, error, refetch } = useDashboardSummary(year, month);

  const onRefresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['budgets'] }),
    ]);
  }, [queryClient]);

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    return (
      <ErrorView
        message="Could not load dashboard. Check your connection."
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return <LoadingSpinner />;

  const hasCategories =
    data.income_categories.length > 0 ||
    data.expense_categories.length > 0 ||
    data.savings_categories.length > 0;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={onRefresh} />
      }
    >
      <MonthSelector />

      {/* Summary cards */}
      <View style={styles.summaryRow}>
        <SummaryCard
          title="Income"
          planned={data.total_planned_income}
          actual={data.total_actual_income}
        />
        <SummaryCard
          title="Expenses"
          planned={data.total_planned_expenses}
          actual={data.total_actual_expenses}
        />
        <SummaryCard
          title="Savings"
          planned={data.total_planned_savings}
          actual={data.total_actual_savings}
        />
      </View>

      {/* Metrics */}
      <Card style={styles.metricsCard}>
        <View style={styles.metricsRow}>
          <MetricItem label="To allocate" value={formatDKK(data.to_be_allocated)} />
          <MetricItem label="Balance" value={formatDKK(data.actual_balance)} />
          <MetricItem
            label="Savings rate"
            value={data.savings_rate ? `${parseFloat(data.savings_rate).toFixed(1)}%` : '\u2014'}
          />
        </View>
      </Card>

      {/* Category breakdowns */}
      {hasCategories ? (
        <>
          <CategorySection title="Income" categories={data.income_categories} />
          <CategorySection title="Expenses" categories={data.expense_categories} />
          <CategorySection title="Savings" categories={data.savings_categories} />
        </>
      ) : (
        <EmptyState message="No budget lines yet. Set planned amounts to see your budget here." />
      )}

      {/* Sign out */}
      <View style={styles.signOutContainer}>
        <Button title="Sign Out" onPress={signOut} variant="ghost" />
      </View>
    </ScrollView>
  );
}

function SummaryCard({
  title,
  planned,
  actual,
}: {
  title: string;
  planned: string;
  actual: string;
}) {
  return (
    <Card title={title} style={styles.summaryCard}>
      <View>
        <Text style={styles.summaryLabel}>Planned</Text>
        <AmountDisplay amount={planned} size="sm" />
      </View>
      <View style={styles.summaryActual}>
        <Text style={styles.summaryLabel}>Actual</Text>
        <AmountDisplay amount={actual} size="sm" />
      </View>
    </Card>
  );
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metricItem}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

function CategorySection({
  title,
  categories,
}: {
  title: string;
  categories: CategoryBudgetActual[];
}) {
  if (categories.length === 0) return null;

  return (
    <View style={styles.categorySection}>
      <Text style={styles.categorySectionTitle}>{title}</Text>
      {categories.map((cat) => (
        <View
          key={cat.category_id}
          style={[
            styles.categoryRow,
            cat.is_over_budget && styles.categoryRowOverBudget,
          ]}
        >
          <Text style={styles.categoryName} numberOfLines={1}>
            {cat.category_name}
          </Text>
          <View style={styles.categoryAmounts}>
            <AmountDisplay amount={cat.actual} size="sm" />
            <Text style={styles.categoryPlanned}>
              / {formatDKK(cat.planned)}
            </Text>
          </View>
        </View>
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
  summaryRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  summaryCard: {
    flex: 1,
  },
  summaryLabel: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginBottom: 2,
  },
  summaryActual: {
    marginTop: spacing.sm,
  },
  metricsCard: {
    marginBottom: spacing.lg,
  },
  metricsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  metricItem: {
    alignItems: 'center',
  },
  metricLabel: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginBottom: 2,
  },
  metricValue: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    fontVariant: ['tabular-nums'],
  },
  categorySection: {
    marginBottom: spacing.lg,
  },
  categorySectionTitle: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  categoryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  categoryRowOverBudget: {
    backgroundColor: colors.dangerLight,
  },
  categoryName: {
    fontSize: fontSize.sm,
    color: colors.text,
    flex: 1,
    marginRight: spacing.sm,
  },
  categoryAmounts: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  categoryPlanned: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginLeft: 4,
  },
  signOutContainer: {
    marginTop: spacing.xxl,
    alignItems: 'center',
  },
});
