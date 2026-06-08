import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';

import { useCreateHousehold } from '@/api/households';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import { colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function CreateHouseholdScreen() {
  const [householdName, setHouseholdName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const createHousehold = useCreateHousehold();

  const handleCreate = () => {
    createHousehold.mutate(
      { household_name: householdName.trim(), display_name: displayName.trim() },
      { onSuccess: () => router.replace('/(onboarding)/categories') },
    );
  };

  return (
    <KeyboardAwareScreen contentContainerStyle={styles.content}>
      <View>
        <Text style={styles.title}>Create Household</Text>
        <Text style={styles.subtitle}>
          Set up your shared household budget
        </Text>

        <TextInput
          label="Household Name"
          placeholder="e.g. Home Budget"
          value={householdName}
          onChangeText={setHouseholdName}
        />

        <TextInput
          label="Your Display Name"
          placeholder="e.g. Andreas"
          value={displayName}
          onChangeText={setDisplayName}
        />

        {createHousehold.error && (
          <Text style={styles.error}>
            {createHousehold.error instanceof Error
              ? createHousehold.error.message
              : 'Failed to create household'}
          </Text>
        )}

        <Button
          title="Create"
          onPress={handleCreate}
          loading={createHousehold.isPending}
          disabled={!householdName.trim() || !displayName.trim()}
        />

        <View style={styles.linkRow}>
          <Text
            style={styles.link}
            onPress={() => router.replace('/(onboarding)/accept-invite')}
          >
            Have an invite? Join an existing household →
          </Text>
        </View>
      </View>
    </KeyboardAwareScreen>
  );
}

const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    justifyContent: 'center',
    padding: spacing.xl,
  },
  title: {
    fontSize: fontSize.xxxl,
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
  linkRow: {
    marginTop: spacing.xl,
    alignItems: 'center',
  },
  link: {
    color: colors.primary,
    fontSize: fontSize.md,
  },
});
