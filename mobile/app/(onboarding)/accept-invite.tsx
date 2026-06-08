import React, { useEffect, useState } from 'react';
import { Alert, Platform, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';

import { useAcceptInvite, useLookupInvite } from '@/api/invites';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import { formatDate } from '@/lib/format';
import { colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

export default function AcceptInviteScreen() {
  const [token, setToken] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    household_name: string;
    expires_at: string;
  } | null>(null);

  const queryClient = useQueryClient();
  const lookupInvite = useLookupInvite();
  const acceptInvite = useAcceptInvite();

  useEffect(() => {
    const trimmed = token.trim();
    if (trimmed.length < 8) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    const handle = setTimeout(() => {
      lookupInvite.mutate(
        { token: trimmed },
        {
          onSuccess: (data) => {
            setPreview({
              household_name: data.household_name,
              expires_at: data.expires_at,
            });
            setPreviewError(null);
          },
          onError: (err: unknown) => {
            setPreview(null);
            setPreviewError(
              err instanceof Error ? err.message : 'Invite token not valid',
            );
          },
        },
      );
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleAccept = () => {
    acceptInvite.mutate(
      { token: token.trim(), display_name: displayName.trim() },
      {
        onSuccess: async () => {
          await queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] });
          await queryClient.invalidateQueries({ queryKey: ['household', 'me'] });
          router.replace('/');
        },
        onError: (err: unknown) => {
          Alert.alert(
            'Could not join',
            err instanceof Error ? err.message : 'Failed to accept invite',
          );
        },
      },
    );
  };

  const canSubmit =
    token.trim().length >= 8 &&
    displayName.trim().length > 0 &&
    !acceptInvite.isPending;

  return (
    <KeyboardAwareScreen contentContainerStyle={styles.content}>
      <View>
        <Text style={styles.title}>Join household</Text>
        <Text style={styles.subtitle}>
          Paste the invite token you received and choose a display name.
        </Text>

        <TextInput
          label="Invite token"
          placeholder="Paste your invite token"
          value={token}
          onChangeText={setToken}
          autoCapitalize="none"
          autoCorrect={false}
          multiline
          style={styles.tokenInput}
        />

        {preview && (
          <Text style={styles.preview}>
            You'll join {preview.household_name} (expires {formatDate(preview.expires_at)})
          </Text>
        )}
        {previewError && <Text style={styles.previewError}>{previewError}</Text>}

        <TextInput
          label="Your display name"
          placeholder="e.g. Andreas"
          value={displayName}
          onChangeText={setDisplayName}
        />

        <Button
          title="Join"
          onPress={handleAccept}
          loading={acceptInvite.isPending}
          disabled={!canSubmit}
        />

        <View style={styles.linkRow}>
          <Text
            style={styles.link}
            onPress={() => router.replace('/(onboarding)/create-household')}
          >
            Create a new household instead →
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
  tokenInput: {
    minHeight: 80,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace' }),
  },
  preview: {
    color: colors.success,
    fontSize: fontSize.sm,
    marginBottom: spacing.lg,
  },
  previewError: {
    color: colors.danger,
    fontSize: fontSize.sm,
    marginBottom: spacing.lg,
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
