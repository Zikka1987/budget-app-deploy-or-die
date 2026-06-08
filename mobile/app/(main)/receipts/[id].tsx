import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';

import {
  useCategorizeReceipt,
  useConfirmReceipt,
  useParseReceipt,
  useReceipt,
  useReviewPayload,
  useUpdateReceiptItem,
} from '@/api/receipts';
import { useCategories } from '@/api/categories';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { formatDKK } from '@/lib/format';
import type { CategoryResponse, ReceiptItemResponse } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function ReceiptDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: receipt, isLoading, error } = useReceipt(id);

  const isOcrComplete = receipt?.status === 'ocr_complete';
  const { data: reviewData } = useReviewPayload(id, isOcrComplete);

  const parseReceipt = useParseReceipt();
  const categorizeReceipt = useCategorizeReceipt();
  const confirmReceipt = useConfirmReceipt();
  const updateItem = useUpdateReceiptItem();
  const { data: expenseCategories } = useCategories('expense');

  const [selectedItem, setSelectedItem] = useState<ReceiptItemResponse | null>(null);
  const [transactionDate, setTransactionDate] = useState('');
  const [imageFailed, setImageFailed] = useState(false);
  const [acceptingAll, setAcceptingAll] = useState(false);

  const handleReloadImage = () => {
    setImageFailed(false);
    if (id) {
      queryClient.invalidateQueries({ queryKey: ['receipts', id] });
    }
  };

  if (isLoading) return <LoadingSpinner />;
  if (error || !receipt) {
    return <ErrorView message="Could not load receipt." />;
  }

  const items = reviewData?.items ?? receipt.items;
  const hasSuggestions = items.some((i) => i.suggested_category_id != null);
  const allReady = items
    .filter((i) => !i.is_excluded)
    .every((i) => i.user_confirmed_category_id != null);
  const nonExcludedCount = items.filter((i) => !i.is_excluded).length;
  const unconfirmedCount = items.filter(
    (i) => !i.is_excluded && i.user_confirmed_category_id == null,
  ).length;
  const acceptableSuggestions = items.filter(
    (i) =>
      !i.is_excluded &&
      i.user_confirmed_category_id == null &&
      i.suggested_category_id != null,
  );
  const needsDateFallback = receipt.receipt_date == null;

  const handleParse = () => {
    if (!id) return;
    parseReceipt.mutate(id, {
      onError: (err) => Alert.alert('Parse failed', err.message),
    });
  };

  const handleCategorize = () => {
    if (!id) return;
    categorizeReceipt.mutate(id, {
      onError: (err) => Alert.alert('Categorize failed', err.message),
    });
  };

  const handleConfirm = () => {
    if (!id) return;
    if (!allReady || nonExcludedCount === 0) {
      Alert.alert('Not ready', 'All non-excluded items must have a confirmed category.');
      return;
    }
    if (needsDateFallback && !transactionDate.trim()) {
      Alert.alert('Date required', 'This receipt has no parsed date. Please enter a transaction date.');
      return;
    }

    const data = needsDateFallback && transactionDate.trim()
      ? { transaction_date: transactionDate.trim() }
      : undefined;

    confirmReceipt.mutate(
      { receiptId: id, data },
      {
        onSuccess: (result) => {
          const msg = result.total_mismatch
            ? `Posted ${result.transactions_created} transaction(s). Note: receipt total differs from item sum.`
            : `Posted ${result.transactions_created} transaction(s) successfully.`;
          Alert.alert('Receipt Posted', msg);
        },
        onError: (err) => Alert.alert('Post failed', err.message),
      },
    );
  };

  const handleSelectCategory = (categoryId: string) => {
    if (!id || !selectedItem) return;
    updateItem.mutate(
      {
        receiptId: id,
        itemId: selectedItem.id,
        data: { user_confirmed_category_id: categoryId },
      },
      {
        onSuccess: () => setSelectedItem(null),
        onError: (err) => Alert.alert('Error', err.message),
      },
    );
  };

  const handleToggleExclude = (item: ReceiptItemResponse) => {
    if (!id) return;
    updateItem.mutate({
      receiptId: id,
      itemId: item.id,
      data: { is_excluded: !item.is_excluded },
    });
  };

  const isAcceptAllDisabled = acceptingAll || confirmReceipt.isPending || updateItem.isPending;
  const isPostDisabled = !allReady || nonExcludedCount === 0 || acceptingAll || updateItem.isPending;

  const handleAcceptAll = async () => {
    if (acceptableSuggestions.length === 0) return;
    setAcceptingAll(true);
    try {
      await Promise.all(
        acceptableSuggestions.map((item) =>
          updateItem.mutateAsync({
            receiptId: id as string,
            itemId: item.id,
            data: { user_confirmed_category_id: item.suggested_category_id! },
          }),
        ),
      );
    } catch (err: any) {
      Alert.alert('Error', err.message ?? 'Failed to accept suggestions');
    } finally {
      setAcceptingAll(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Receipt image */}
      {receipt.image_url && !imageFailed && (
        <Image
          source={{ uri: receipt.image_url }}
          style={styles.receiptImage}
          resizeMode="contain"
          onError={() => setImageFailed(true)}
        />
      )}
      {receipt.image_url && imageFailed && (
        <View style={styles.imageFallback}>
          <Text style={styles.imageFallbackText}>Image unavailable.</Text>
          <Pressable onPress={handleReloadImage} hitSlop={8}>
            <Text style={styles.imageFallbackAction}>Tap to reload</Text>
          </Pressable>
        </View>
      )}

      {/* Metadata */}
      <View style={styles.metaSection}>
        {receipt.store_name && (
          <Text style={styles.storeName}>{receipt.store_name}</Text>
        )}
        {receipt.receipt_date && (
          <Text style={styles.metaText}>Date: {receipt.receipt_date}</Text>
        )}
        {receipt.total_amount != null && (
          <Text style={styles.metaText}>Total: {formatDKK(receipt.total_amount)}</Text>
        )}
      </View>

      {/* Status: uploaded */}
      {receipt.status === 'uploaded' && (
        <Button
          title="Parse Receipt"
          onPress={handleParse}
          loading={parseReceipt.isPending}
        />
      )}

      {/* Status: processing */}
      {receipt.status === 'processing' && (
        <View style={styles.processingSection}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.processingText}>Processing receipt...</Text>
        </View>
      )}

      {/* Status: failed */}
      {receipt.status === 'failed' && (
        <View style={styles.failedSection}>
          <Text style={styles.failedText}>Parsing failed. You can retry.</Text>
          <Button
            title="Retry Parse"
            onPress={handleParse}
            loading={parseReceipt.isPending}
          />
        </View>
      )}

      {/* Status: ocr_complete — review mode */}
      {isOcrComplete && (
        <>
          {/* Duplicate warning */}
          {receipt.duplicate_candidates.length > 0 && (
            <View style={styles.warningBanner}>
              <Text style={styles.warningText}>
                Possible duplicate detected ({receipt.duplicate_candidates.length} similar receipt{receipt.duplicate_candidates.length > 1 ? 's' : ''})
              </Text>
            </View>
          )}

          {/* Categorize button */}
          <Button
            title={hasSuggestions ? 'Re-categorize' : 'Categorize Items'}
            onPress={handleCategorize}
            loading={categorizeReceipt.isPending}
            variant={hasSuggestions ? 'secondary' : 'primary'}
            style={styles.actionButton}
          />

          {/* Items list */}
          <Text style={styles.sectionTitle}>Items</Text>
          {items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              onPress={() => setSelectedItem(item)}
              onToggleExclude={() => handleToggleExclude(item)}
            />
          ))}

          {/* Date fallback input */}
          {needsDateFallback && (
            <TextInput
              label="Transaction date (YYYY-MM-DD, required — no date parsed)"
              value={transactionDate}
              onChangeText={setTransactionDate}
              placeholder="2026-04-19"
            />
          )}

          <View style={styles.postSection}>
            {acceptableSuggestions.length > 0 && (
              <Button
                title={`Accept ${acceptableSuggestions.length} suggestion${acceptableSuggestions.length !== 1 ? 's' : ''}`}
                onPress={handleAcceptAll}
                loading={acceptingAll}
                disabled={isAcceptAllDisabled}
                variant="secondary"
              />
            )}
            {nonExcludedCount === 0 ? (
              <Text style={styles.confirmHint}>
                At least one item must be included before posting this receipt.
              </Text>
            ) : !allReady && unconfirmedCount > 0 ? (
              <Text style={styles.confirmHint}>
                {unconfirmedCount} item{unconfirmedCount !== 1 ? 's' : ''} still need{unconfirmedCount === 1 ? 's' : ''} confirmation before posting.
              </Text>
            ) : null}
            <Button
              title={
                !allReady && unconfirmedCount > 0
                  ? `Confirm ${unconfirmedCount} item${unconfirmedCount !== 1 ? 's' : ''} to post`
                  : 'Post Receipt'
              }
              onPress={handleConfirm}
              loading={confirmReceipt.isPending}
              disabled={isPostDisabled}
            />
          </View>
        </>
      )}

      {/* Status: posted or reviewed */}
      {(receipt.status === 'posted' || receipt.status === 'reviewed') && (
        <>
          <View style={styles.postedBadge}>
            <Text style={styles.postedText}>Receipt posted</Text>
          </View>
          <Text style={styles.sectionTitle}>Items</Text>
          {items.map((item) => (
            <View key={item.id} style={styles.itemRow}>
              <View style={styles.itemLeft}>
                <Text style={styles.itemDescription} numberOfLines={1}>
                  {item.description}
                </Text>
                <Text style={styles.itemCategory}>
                  {item.user_confirmed_category_name ?? item.suggested_category_name ?? '—'}
                </Text>
              </View>
              <Text style={styles.itemAmount}>{formatDKK(item.total_price)}</Text>
            </View>
          ))}
        </>
      )}

      {/* Category picker modal */}
      <Modal visible={!!selectedItem} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>
              {selectedItem?.description}
            </Text>
            <Text style={styles.modalSubtitle}>Select category</Text>
            <ScrollView style={styles.categoryList}>
              {expenseCategories
                ?.filter((c: CategoryResponse) => !c.archived_at)
                .map((cat: CategoryResponse) => (
                  <Pressable
                    key={cat.id}
                    style={[
                      styles.categoryOption,
                      selectedItem?.user_confirmed_category_id === cat.id &&
                        styles.categoryOptionSelected,
                    ]}
                    onPress={() => handleSelectCategory(cat.id)}
                  >
                    <Text
                      style={[
                        styles.categoryOptionText,
                        selectedItem?.user_confirmed_category_id === cat.id &&
                          styles.categoryOptionTextSelected,
                      ]}
                    >
                      {cat.name}
                    </Text>
                  </Pressable>
                ))}
            </ScrollView>
            <Button
              title="Cancel"
              onPress={() => setSelectedItem(null)}
              variant="ghost"
              style={styles.modalCancel}
            />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function ItemRow({
  item,
  onPress,
  onToggleExclude,
}: {
  item: ReceiptItemResponse;
  onPress: () => void;
  onToggleExclude: () => void;
}) {
  const categoryLabel = item.user_confirmed_category_name
    ? item.user_confirmed_category_name
    : item.suggested_category_name
      ? `${item.suggested_category_name} (suggested)`
      : 'No category';

  const categoryColor = item.user_confirmed_category_id
    ? colors.text
    : item.suggested_category_id
      ? colors.textSecondary
      : colors.danger;

  return (
    <View style={[styles.itemRow, item.is_excluded && styles.itemRowExcluded]}>
      <Pressable style={styles.itemLeft} onPress={onPress}>
        <Text
          style={[styles.itemDescription, item.is_excluded && styles.itemExcludedText]}
          numberOfLines={1}
        >
          {item.description}
        </Text>
        <Text style={[styles.itemCategory, { color: categoryColor }]}>
          {categoryLabel}
        </Text>
        {item.requires_review && !item.is_excluded && (
          <Text style={styles.reviewHint}>Needs review</Text>
        )}
      </Pressable>
      <View style={styles.itemRight}>
        <Text
          style={[styles.itemAmount, item.is_excluded && styles.itemExcludedText]}
        >
          {formatDKK(item.total_price)}
        </Text>
        <Pressable onPress={onToggleExclude} hitSlop={8}>
          <Text style={styles.excludeToggle}>
            {item.is_excluded ? 'Include' : 'Exclude'}
          </Text>
        </Pressable>
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
  receiptImage: {
    width: '100%',
    height: 200,
    borderRadius: borderRadius.md,
    backgroundColor: colors.borderLight,
    marginBottom: spacing.lg,
  },
  imageFallback: {
    width: '100%',
    height: 200,
    borderRadius: borderRadius.md,
    backgroundColor: colors.borderLight,
    marginBottom: spacing.lg,
    justifyContent: 'center',
    alignItems: 'center',
    gap: spacing.xs,
  },
  imageFallbackText: {
    fontSize: fontSize.sm,
    color: colors.textTertiary,
  },
  imageFallbackAction: {
    fontSize: fontSize.sm,
    color: colors.primary,
    fontWeight: fontWeight.semibold,
  },
  metaSection: {
    marginBottom: spacing.lg,
  },
  storeName: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  metaText: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginBottom: 2,
  },
  processingSection: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  processingText: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginTop: spacing.md,
  },
  failedSection: {
    gap: spacing.md,
  },
  failedText: {
    fontSize: fontSize.sm,
    color: colors.danger,
  },
  warningBanner: {
    backgroundColor: colors.warningLight,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.md,
  },
  warningText: {
    fontSize: fontSize.sm,
    color: colors.warning,
    fontWeight: fontWeight.medium,
  },
  actionButton: {
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
  itemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  itemRowExcluded: {
    opacity: 0.5,
  },
  itemLeft: {
    flex: 1,
    marginRight: spacing.md,
  },
  itemDescription: {
    fontSize: fontSize.sm,
    color: colors.text,
  },
  itemExcludedText: {
    textDecorationLine: 'line-through',
  },
  itemCategory: {
    fontSize: fontSize.xs,
    marginTop: 2,
  },
  reviewHint: {
    fontSize: fontSize.xs,
    color: colors.warning,
    fontWeight: fontWeight.medium,
    marginTop: 2,
  },
  itemRight: {
    alignItems: 'flex-end',
  },
  itemAmount: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    fontVariant: ['tabular-nums'],
  },
  excludeToggle: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  postSection: {
    marginTop: spacing.lg,
    gap: spacing.sm,
  },
  confirmHint: {
    textAlign: 'center',
    fontSize: fontSize.sm,
    color: colors.textSecondary,
  },
  postedBadge: {
    backgroundColor: colors.successLight,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.lg,
    alignItems: 'center',
  },
  postedText: {
    fontSize: fontSize.sm,
    color: colors.success,
    fontWeight: fontWeight.medium,
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
    maxHeight: '70%',
  },
  modalTitle: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  modalSubtitle: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
  categoryList: {
    maxHeight: 300,
  },
  categoryOption: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
    backgroundColor: colors.surface,
  },
  categoryOptionSelected: {
    backgroundColor: colors.primaryLight,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  categoryOptionText: {
    fontSize: fontSize.sm,
    color: colors.text,
  },
  categoryOptionTextSelected: {
    color: colors.primary,
    fontWeight: fontWeight.semibold,
  },
  modalCancel: {
    marginTop: spacing.sm,
  },
});
