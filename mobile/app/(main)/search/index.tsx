import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useCategories } from '@/api/categories';
import {
  useSearchReceipts,
  useSearchTransactions,
  type ReceiptSearchFilters,
  type TransactionSearchFilters,
} from '@/api/search';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorView } from '@/components/ui/ErrorView';
import { useDebouncedValue } from '@/lib/useDebouncedValue';
import { formatDKK, formatDate } from '@/lib/format';
import type {
  CategoryResponse,
  ReceiptSearchResult,
  ReceiptStatus,
  TransactionSearchResult,
  TransactionSource,
  TransactionType,
} from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

type Mode = 'receipts' | 'transactions';

const RECEIPT_STATUSES: ReceiptStatus[] = [
  'uploaded',
  'processing',
  'ocr_complete',
  'reviewed',
  'posted',
  'failed',
];

const STATUS_LABEL: Record<ReceiptStatus, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  ocr_complete: 'OCR Complete',
  reviewed: 'Reviewed',
  posted: 'Posted',
  failed: 'Failed',
};

const TRANSACTION_TYPES: TransactionType[] = ['income', 'expense', 'savings'];
const TRANSACTION_SOURCES: TransactionSource[] = [
  'manual_income',
  'manual_expense',
  'manual_savings',
  'receipt',
  'savings_proposal',
];

const SOURCE_LABEL: Record<TransactionSource, string> = {
  manual_income: 'Manual income',
  manual_expense: 'Manual expense',
  manual_savings: 'Manual savings',
  receipt: 'Receipt',
  savings_proposal: 'Savings proposal',
};

const TYPE_LABEL: Record<TransactionType, string> = {
  income: 'Income',
  expense: 'Expense',
  savings: 'Savings',
};

const TYPE_BADGE: Record<TransactionType, { bg: string; fg: string }> = {
  income: { bg: colors.successLight, fg: colors.success },
  expense: { bg: colors.dangerLight, fg: colors.danger },
  savings: { bg: colors.primaryLight, fg: colors.primary },
};

const STATUS_BADGE: Record<ReceiptStatus, { bg: string; fg: string }> = {
  uploaded: { bg: colors.borderLight, fg: colors.textSecondary },
  processing: { bg: colors.primaryLight, fg: colors.primary },
  ocr_complete: { bg: colors.warningLight, fg: colors.warning },
  reviewed: { bg: colors.successLight, fg: colors.success },
  posted: { bg: colors.successLight, fg: colors.success },
  failed: { bg: colors.dangerLight, fg: colors.danger },
};

export default function SearchScreen() {
  const [mode, setMode] = useState<Mode>('receipts');
  const [receiptFilters, setReceiptFilters] = useState<ReceiptSearchFilters>({});
  const [transactionFilters, setTransactionFilters] =
    useState<TransactionSearchFilters>({});

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.segmentRow}>
          <Pressable
            style={[styles.segmentPill, mode === 'receipts' && styles.segmentPillActive]}
            onPress={() => setMode('receipts')}
          >
            <Text
              style={[
                styles.segmentText,
                mode === 'receipts' && styles.segmentTextActive,
              ]}
            >
              Receipts
            </Text>
          </Pressable>
          <Pressable
            style={[
              styles.segmentPill,
              mode === 'transactions' && styles.segmentPillActive,
            ]}
            onPress={() => setMode('transactions')}
          >
            <Text
              style={[
                styles.segmentText,
                mode === 'transactions' && styles.segmentTextActive,
              ]}
            >
              Transactions
            </Text>
          </Pressable>
        </View>

        {mode === 'receipts' ? (
          <ReceiptSearchSection
            filters={receiptFilters}
            onChangeFilters={setReceiptFilters}
          />
        ) : (
          <TransactionSearchSection
            filters={transactionFilters}
            onChangeFilters={setTransactionFilters}
          />
        )}
      </ScrollView>
    </View>
  );
}

interface ReceiptSearchSectionProps {
  filters: ReceiptSearchFilters;
  onChangeFilters: (next: ReceiptSearchFilters) => void;
}

function ReceiptSearchSection({
  filters,
  onChangeFilters,
}: ReceiptSearchSectionProps) {
  const [merchantInput, setMerchantInput] = useState(filters.merchant ?? '');
  const debouncedMerchant = useDebouncedValue(merchantInput, 250);

  useEffect(() => {
    const next = debouncedMerchant.trim() || undefined;
    if (filters.merchant !== next) {
      onChangeFilters({ ...filters, merchant: next });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedMerchant]);

  const { data: categories } = useCategories('expense');

  const query = useSearchReceipts(filters);
  const results = useMemo(
    () => query.data?.pages.flatMap((p) => p.results) ?? [],
    [query.data],
  );
  const total = query.data?.pages[0]?.total ?? 0;

  const updateFilter = <K extends keyof ReceiptSearchFilters>(
    key: K,
    value: ReceiptSearchFilters[K],
  ) => onChangeFilters({ ...filters, [key]: value });

  const clearFilters = () => {
    setMerchantInput('');
    onChangeFilters({});
  };

  return (
    <View>
      <TextInput
        label="Merchant"
        value={merchantInput}
        onChangeText={setMerchantInput}
        placeholder="Store name"
      />

      <Text style={styles.filterLabel}>Status</Text>
      <View style={styles.chipRow}>
        <FilterChip
          label="All"
          active={!filters.status}
          onPress={() => updateFilter('status', undefined)}
        />
        {RECEIPT_STATUSES.map((s) => (
          <FilterChip
            key={s}
            label={STATUS_LABEL[s]}
            active={filters.status === s}
            onPress={() => updateFilter('status', s)}
          />
        ))}
      </View>

      <Text style={styles.filterLabel}>Category</Text>
      <CategoryChips
        categories={categories ?? []}
        selectedId={filters.category_id}
        onSelect={(id) => updateFilter('category_id', id)}
      />

      <View style={styles.dateRow}>
        <View style={styles.dateField}>
          <TextInput
            label="From (YYYY-MM-DD)"
            value={filters.date_from ?? ''}
            onChangeText={(v) => updateFilter('date_from', v || undefined)}
            placeholder="2026-01-01"
          />
        </View>
        <View style={styles.dateField}>
          <TextInput
            label="To (YYYY-MM-DD)"
            value={filters.date_to ?? ''}
            onChangeText={(v) => updateFilter('date_to', v || undefined)}
            placeholder="2026-12-31"
          />
        </View>
      </View>

      <View style={styles.dateRow}>
        <View style={styles.dateField}>
          <TextInput
            label="Min amount"
            value={filters.amount_min ?? ''}
            onChangeText={(v) => updateFilter('amount_min', v || undefined)}
            keyboardType="decimal-pad"
            placeholder="0"
          />
        </View>
        <View style={styles.dateField}>
          <TextInput
            label="Max amount"
            value={filters.amount_max ?? ''}
            onChangeText={(v) => updateFilter('amount_max', v || undefined)}
            keyboardType="decimal-pad"
            placeholder="10000"
          />
        </View>
      </View>

      <Button
        title="Clear filters"
        variant="ghost"
        onPress={clearFilters}
        style={styles.clearButton}
      />

      <ResultStatus
        isLoading={query.isLoading}
        error={query.error}
        loadedCount={results.length}
        total={total}
      />

      {!query.isLoading && !query.error && results.length === 0 && (
        <EmptyState message="No receipts match." />
      )}

      {results.map((item) => (
        <ReceiptRow key={item.id} item={item} />
      ))}

      {query.hasNextPage && (
        <Button
          title={query.isFetchingNextPage ? 'Loading…' : 'Load more'}
          variant="secondary"
          onPress={() => query.fetchNextPage()}
          loading={query.isFetchingNextPage}
          style={styles.loadMore}
        />
      )}
    </View>
  );
}

interface TransactionSearchSectionProps {
  filters: TransactionSearchFilters;
  onChangeFilters: (next: TransactionSearchFilters) => void;
}

function TransactionSearchSection({
  filters,
  onChangeFilters,
}: TransactionSearchSectionProps) {
  const { data: categories } = useCategories(filters.type);

  const query = useSearchTransactions(filters);
  const results = useMemo(
    () => query.data?.pages.flatMap((p) => p.results) ?? [],
    [query.data],
  );
  const total = query.data?.pages[0]?.total ?? 0;

  const updateFilter = <K extends keyof TransactionSearchFilters>(
    key: K,
    value: TransactionSearchFilters[K],
  ) => onChangeFilters({ ...filters, [key]: value });

  const clearFilters = () => onChangeFilters({});

  return (
    <View>
      <Text style={styles.filterLabel}>Type</Text>
      <View style={styles.chipRow}>
        <FilterChip
          label="All"
          active={!filters.type}
          onPress={() => onChangeFilters({ ...filters, type: undefined, category_id: undefined })}
        />
        {TRANSACTION_TYPES.map((t) => (
          <FilterChip
            key={t}
            label={TYPE_LABEL[t]}
            active={filters.type === t}
            onPress={() =>
              onChangeFilters({ ...filters, type: t, category_id: undefined })
            }
          />
        ))}
      </View>

      <Text style={styles.filterLabel}>Source</Text>
      <View style={styles.chipRow}>
        <FilterChip
          label="All"
          active={!filters.source}
          onPress={() => updateFilter('source', undefined)}
        />
        {TRANSACTION_SOURCES.map((s) => (
          <FilterChip
            key={s}
            label={SOURCE_LABEL[s]}
            active={filters.source === s}
            onPress={() => updateFilter('source', s)}
          />
        ))}
      </View>

      <Text style={styles.filterLabel}>Category</Text>
      <CategoryChips
        categories={categories ?? []}
        selectedId={filters.category_id}
        onSelect={(id) => updateFilter('category_id', id)}
      />

      <View style={styles.dateRow}>
        <View style={styles.dateField}>
          <TextInput
            label="From (YYYY-MM-DD)"
            value={filters.date_from ?? ''}
            onChangeText={(v) => updateFilter('date_from', v || undefined)}
            placeholder="2026-01-01"
          />
        </View>
        <View style={styles.dateField}>
          <TextInput
            label="To (YYYY-MM-DD)"
            value={filters.date_to ?? ''}
            onChangeText={(v) => updateFilter('date_to', v || undefined)}
            placeholder="2026-12-31"
          />
        </View>
      </View>

      <View style={styles.dateRow}>
        <View style={styles.dateField}>
          <TextInput
            label="Min amount"
            value={filters.amount_min ?? ''}
            onChangeText={(v) => updateFilter('amount_min', v || undefined)}
            keyboardType="decimal-pad"
            placeholder="0"
          />
        </View>
        <View style={styles.dateField}>
          <TextInput
            label="Max amount"
            value={filters.amount_max ?? ''}
            onChangeText={(v) => updateFilter('amount_max', v || undefined)}
            keyboardType="decimal-pad"
            placeholder="10000"
          />
        </View>
      </View>

      <Button
        title="Clear filters"
        variant="ghost"
        onPress={clearFilters}
        style={styles.clearButton}
      />

      <ResultStatus
        isLoading={query.isLoading}
        error={query.error}
        loadedCount={results.length}
        total={total}
      />

      {!query.isLoading && !query.error && results.length === 0 && (
        <EmptyState message="No transactions match." />
      )}

      {results.map((item) => (
        <TransactionRow key={item.id} item={item} />
      ))}

      {query.hasNextPage && (
        <Button
          title={query.isFetchingNextPage ? 'Loading…' : 'Load more'}
          variant="secondary"
          onPress={() => query.fetchNextPage()}
          loading={query.isFetchingNextPage}
          style={styles.loadMore}
        />
      )}
    </View>
  );
}

interface FilterChipProps {
  label: string;
  active: boolean;
  onPress: () => void;
}

function FilterChip({ label, active, onPress }: FilterChipProps) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

interface CategoryChipsProps {
  categories: CategoryResponse[];
  selectedId?: string;
  onSelect: (id: string | undefined) => void;
}

function CategoryChips({ categories, selectedId, onSelect }: CategoryChipsProps) {
  const active = categories.filter((c) => !c.archived_at);
  return (
    <View style={styles.chipRow}>
      <FilterChip
        label="All"
        active={!selectedId}
        onPress={() => onSelect(undefined)}
      />
      {active.map((c) => (
        <FilterChip
          key={c.id}
          label={c.name}
          active={selectedId === c.id}
          onPress={() => onSelect(c.id)}
        />
      ))}
    </View>
  );
}

interface ResultStatusProps {
  isLoading: boolean;
  error: Error | null;
  loadedCount: number;
  total: number;
}

function ResultStatus({ isLoading, error, loadedCount, total }: ResultStatusProps) {
  if (isLoading && loadedCount === 0) return <LoadingSpinner />;
  if (error) return <ErrorView message={error.message} />;
  if (loadedCount === 0) return null;
  return (
    <Text style={styles.resultCount}>
      Showing {loadedCount} of {total}
    </Text>
  );
}

function ReceiptRow({ item }: { item: ReceiptSearchResult }) {
  const config = STATUS_BADGE[item.status];
  const displayName = item.store_name || 'Receipt';
  return (
    <Pressable
      style={styles.row}
      onPress={() =>
        router.push({
          pathname: '/(main)/receipts/[id]',
          params: { id: item.id },
        })
      }
    >
      <View style={styles.rowLeft}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {displayName}
        </Text>
        {item.receipt_date && (
          <Text style={styles.rowSub}>{formatDate(item.receipt_date)}</Text>
        )}
      </View>
      <View style={styles.rowRight}>
        {item.total_amount != null && (
          <Text style={styles.amount}>{formatDKK(item.total_amount)}</Text>
        )}
        <View style={[styles.badge, { backgroundColor: config.bg }]}>
          <Text style={[styles.badgeText, { color: config.fg }]}>
            {STATUS_LABEL[item.status]}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

function TransactionRow({ item }: { item: TransactionSearchResult }) {
  const config = TYPE_BADGE[item.type];
  const sub = item.description || item.store_name || '';
  return (
    <View style={styles.row}>
      <View style={styles.rowLeft}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {item.category_name}
        </Text>
        <Text style={styles.rowSub}>{formatDate(item.effective_date)}</Text>
        {sub.length > 0 && (
          <Text style={styles.rowSub} numberOfLines={1}>
            {sub}
          </Text>
        )}
      </View>
      <View style={styles.rowRight}>
        <Text style={styles.amount}>{formatDKK(item.amount)}</Text>
        <View style={[styles.badge, { backgroundColor: config.bg }]}>
          <Text style={[styles.badgeText, { color: config.fg }]}>
            {TYPE_LABEL[item.type]}
          </Text>
        </View>
      </View>
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
  filterLabel: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
    marginTop: spacing.sm,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  chip: {
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
  },
  chipActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  chipText: {
    fontSize: fontSize.xs,
    color: colors.text,
  },
  chipTextActive: {
    color: colors.textInverse,
    fontWeight: fontWeight.semibold,
  },
  dateRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  dateField: {
    flex: 1,
  },
  clearButton: {
    marginBottom: spacing.md,
  },
  resultCount: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
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
  rowTitle: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
  },
  rowSub: {
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
  badge: {
    paddingVertical: 2,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  badgeText: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
  },
  loadMore: {
    marginTop: spacing.md,
  },
});
