import React, { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import {
  useArchiveCategory,
  useCategories,
  useCreateCategory,
  useUpdateCategory,
} from '@/api/categories';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import type { CategoryResponse, TransactionType } from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

const CATEGORY_TYPES: { type: TransactionType; label: string }[] = [
  { type: 'income', label: 'Income' },
  { type: 'expense', label: 'Expense' },
  { type: 'savings', label: 'Savings' },
];

export default function ManageCategoriesScreen() {
  return (
    <KeyboardAwareScreen
      backgroundColor={colors.surface}
      contentContainerStyle={styles.content}
    >
      {CATEGORY_TYPES.map(({ type, label }) => (
        <CategorySection key={type} type={type} label={label} />
      ))}
    </KeyboardAwareScreen>
  );
}

function CategorySection({
  type,
  label,
}: {
  type: TransactionType;
  label: string;
}) {
  const { data: categories, isLoading } = useCategories(type);
  const createCategory = useCreateCategory();
  const updateCategory = useUpdateCategory();
  const archiveCategory = useArchiveCategory();

  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');

  const activeCount = categories?.length ?? 0;
  const lowerLabel = label.toLowerCase();

  const handleAdd = () => {
    const trimmed = newName.trim();
    if (!trimmed) return;
    createCategory.mutate(
      { type, name: trimmed },
      {
        onSuccess: () => {
          setNewName('');
          setAdding(false);
        },
        onError: (err) => Alert.alert('Could not add', err.message),
      },
    );
  };

  const handleArchive = (cat: CategoryResponse) => {
    if (activeCount <= 1) {
      Alert.alert(
        `Can't archive`,
        `This is your only active ${lowerLabel} category. ` +
          `Add another ${lowerLabel} category first, then you can archive this one.`,
        [{ text: 'OK' }],
      );
      return;
    }
    Alert.alert(
      'Archive category',
      `Archive "${cat.name}"? Past transactions keep this name. ` +
        `It won't appear in pickers anymore.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Archive',
          style: 'destructive',
          onPress: () =>
            archiveCategory.mutate(cat.id, {
              onError: (err) => Alert.alert('Error', err.message),
            }),
        },
      ],
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
          {categories?.map((cat) => (
            <CategoryRow
              key={cat.id}
              category={cat}
              updateCategory={updateCategory}
              onArchive={() => handleArchive(cat)}
            />
          ))}

          {categories?.length === 0 && !adding && (
            <Text style={styles.empty}>No {lowerLabel} categories yet</Text>
          )}
        </>
      )}

      {adding ? (
        <View style={styles.addForm}>
          <TextInput
            label={`${label} category name`}
            placeholder={`e.g. ${
              type === 'income'
                ? 'Salary'
                : type === 'expense'
                  ? 'Groceries'
                  : 'General Savings'
            }`}
            value={newName}
            onChangeText={setNewName}
            autoFocus
          />
          <View style={styles.addActions}>
            <Button
              title="Save"
              onPress={handleAdd}
              loading={createCategory.isPending}
              disabled={!newName.trim()}
              style={styles.addButton}
            />
            <Button
              title="Cancel"
              onPress={() => {
                setAdding(false);
                setNewName('');
              }}
              variant="ghost"
              style={styles.addButton}
            />
          </View>
        </View>
      ) : (
        <Pressable onPress={() => setAdding(true)} style={styles.addTrigger}>
          <Text style={styles.addTriggerText}>+ Add {lowerLabel} category</Text>
        </Pressable>
      )}
    </View>
  );
}

function CategoryRow({
  category,
  updateCategory,
  onArchive,
}: {
  category: CategoryResponse;
  updateCategory: ReturnType<typeof useUpdateCategory>;
  onArchive: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(category.name);

  const trimmed = draftName.trim();
  const canSave = trimmed.length > 0 && trimmed !== category.name;

  const startEdit = () => {
    setDraftName(category.name);
    setEditing(true);
  };

  const cancelEdit = () => {
    setDraftName(category.name);
    setEditing(false);
  };

  const saveEdit = () => {
    if (!canSave) return;
    updateCategory.mutate(
      { categoryId: category.id, data: { name: trimmed } },
      {
        onSuccess: () => setEditing(false),
        onError: (err) => Alert.alert('Could not rename', err.message),
      },
    );
  };

  if (editing) {
    return (
      <View style={styles.editRow}>
        <TextInput
          label="Category name"
          value={draftName}
          onChangeText={setDraftName}
          autoFocus
          autoCapitalize="sentences"
        />
        <View style={styles.editActions}>
          <Button
            title="Save"
            onPress={saveEdit}
            loading={updateCategory.isPending}
            disabled={!canSave}
            style={styles.editButton}
          />
          <Button
            title="Cancel"
            onPress={cancelEdit}
            variant="ghost"
            style={styles.editButton}
          />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.row}>
      <Pressable
        onPress={startEdit}
        style={styles.rowMain}
        hitSlop={8}
      >
        <Text style={styles.rowName}>{category.name}</Text>
        <Text style={styles.rowEditHint}>Tap to rename</Text>
      </Pressable>
      <Pressable onPress={onArchive} hitSlop={8} style={styles.archiveButton}>
        <Text style={styles.archiveText}>Archive</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: spacing.lg,
  },
  section: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginBottom: spacing.lg,
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
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  rowMain: {
    flex: 1,
  },
  rowName: {
    fontSize: fontSize.md,
    color: colors.text,
  },
  rowEditHint: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginTop: 2,
  },
  archiveButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  archiveText: {
    fontSize: fontSize.sm,
    color: colors.danger,
    fontWeight: fontWeight.medium,
  },
  editRow: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.md,
    marginBottom: spacing.xs,
  },
  editActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  editButton: {
    flex: 1,
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
});
