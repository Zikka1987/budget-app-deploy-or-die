import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput as RNTextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { useHousehold } from '@/api/households';
import { useInvites, useCreateInvite, useRevokeInvite } from '@/api/invites';
import {
  useHouseholdSettings,
  useUpdateHouseholdSettings,
} from '@/api/settings';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { KeyboardAwareScreen } from '@/components/KeyboardAwareScreen';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { TextInput } from '@/components/ui/TextInput';
import { useAuth } from '@/contexts/auth-context';
import { formatDate } from '@/lib/format';
import {
  borderRadius,
  colors,
  fontSize,
  fontWeight,
  spacing,
} from '@/theme/tokens';
import type { InviteSummary } from '@/types/api';

export default function SettingsScreen() {
  const { user, signOut } = useAuth();
  const household = useHousehold();
  const settings = useHouseholdSettings();
  const updateSettings = useUpdateHouseholdSettings();

  const pendingInvites = useInvites('pending');
  const acceptedInvites = useInvites('accepted');
  const createInvite = useCreateInvite();
  const revokeInvite = useRevokeInvite();

  // Settings form state — synced from server data when it arrives.
  const [shiftLate, setShiftLate] = useState(false);
  const [cutoffDay, setCutoffDay] = useState('');

  useEffect(() => {
    if (settings.data) {
      setShiftLate(settings.data.shift_late_income);
      setCutoffDay(
        settings.data.late_income_cutoff_day != null
          ? String(settings.data.late_income_cutoff_day)
          : '',
      );
    }
  }, [settings.data]);

  const settingsDirty = useMemo(() => {
    if (!settings.data) return false;
    const serverDay =
      settings.data.late_income_cutoff_day != null
        ? String(settings.data.late_income_cutoff_day)
        : '';
    return (
      shiftLate !== settings.data.shift_late_income || cutoffDay !== serverDay
    );
  }, [settings.data, shiftLate, cutoffDay]);

  const handleSaveSettings = () => {
    if (shiftLate) {
      const n = parseInt(cutoffDay, 10);
      if (!Number.isFinite(n) || n < 1 || n > 28) {
        Alert.alert('Invalid input', 'Cutoff day must be between 1 and 28.');
        return;
      }
    }
    updateSettings.mutate(
      {
        shift_late_income: shiftLate,
        late_income_cutoff_day: shiftLate ? parseInt(cutoffDay, 10) : null,
      },
      {
        onError: (err) => Alert.alert('Could not save', err.message),
      },
    );
  };

  // Invite create form
  const [inviteEmail, setInviteEmail] = useState('');
  const [createdToken, setCreatedToken] = useState<string | null>(null);

  const handleSendInvite = () => {
    const email = inviteEmail.trim();
    if (!email) {
      Alert.alert('Missing email', 'Enter the email of the person to invite.');
      return;
    }
    createInvite.mutate(
      { email },
      {
        onSuccess: (resp) => {
          setCreatedToken(resp.token);
          setInviteEmail('');
        },
        onError: (err) => Alert.alert('Could not send invite', err.message),
      },
    );
  };

  const handleRevoke = (invite: InviteSummary) => {
    Alert.alert(
      'Revoke invite',
      `Revoke the invite sent to ${invite.email}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Revoke',
          style: 'destructive',
          onPress: () =>
            revokeInvite.mutate(invite.id, {
              onError: (err) => Alert.alert('Error', err.message),
            }),
        },
      ],
    );
  };

  const handleSignOut = () => {
    Alert.alert('Sign out', 'Sign out of this device?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: () => {
          signOut().catch((err: Error) =>
            Alert.alert('Error', err.message),
          );
        },
      },
    ]);
  };

  if (household.isLoading || settings.isLoading) {
    return <LoadingSpinner />;
  }

  const accepted = acceptedInvites.data?.invites ?? [];
  const pending = pendingInvites.data?.invites ?? [];
  const memberCount = 1 + accepted.length;
  const canInvite = memberCount < 2;

  return (
    <KeyboardAwareScreen
      backgroundColor={colors.surface}
      contentContainerStyle={styles.content}
    >
      {/* Household card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Household</Text>
        {household.data ? (
          <>
            <Text style={styles.householdName}>{household.data.name}</Text>
            <Text style={styles.metaText}>
              Created {formatDate(household.data.created_at)}
            </Text>
          </>
        ) : (
          <Text style={styles.metaText}>Could not load household.</Text>
        )}
      </View>

      {/* Preferences card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Late income shift</Text>
        <Text style={styles.bodyText}>
          When enabled, income recorded on or after the cutoff day is rolled
          into next month&apos;s budget instead of the current month.
        </Text>

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Enable late income shift</Text>
          <Switch
            value={shiftLate}
            onValueChange={setShiftLate}
            trackColor={{ false: colors.border, true: colors.primaryLight }}
            thumbColor={shiftLate ? colors.primary : colors.background}
          />
        </View>

        <Text style={styles.fieldLabel}>Cutoff day (1–28)</Text>
        <RNTextInput
          style={[
            styles.dayInput,
            !shiftLate && styles.dayInputDisabled,
          ]}
          value={cutoffDay}
          onChangeText={setCutoffDay}
          editable={shiftLate}
          keyboardType="number-pad"
          maxLength={2}
          placeholder="e.g. 25"
          placeholderTextColor={colors.textTertiary}
        />

        <Button
          title="Save"
          onPress={handleSaveSettings}
          disabled={!settingsDirty}
          loading={updateSettings.isPending}
          style={styles.saveButton}
        />
      </View>

      {/* Categories navigation */}
      <Pressable
        onPress={() => router.push('/(main)/settings/categories')}
        style={styles.card}
      >
        <View style={styles.navRow}>
          <View style={styles.navMain}>
            <Text style={styles.cardTitle}>Categories</Text>
            <Text style={styles.metaText}>
              Add, rename, or archive income, expense, and savings categories.
            </Text>
          </View>
          <Text style={styles.navChevron}>{'›'}</Text>
        </View>
      </Pressable>

      {/* Members section */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Members ({memberCount}/2)</Text>
        <View style={styles.memberRow}>
          <View style={styles.memberMain}>
            <Text style={styles.memberName}>You</Text>
            <Text style={styles.memberEmail}>{user?.email ?? '—'}</Text>
          </View>
          <Text style={styles.memberMeta}>this device</Text>
        </View>
        {accepted.map((inv) => (
          <View key={inv.id} style={styles.memberRow}>
            <View style={styles.memberMain}>
              <Text style={styles.memberName}>{inv.email}</Text>
              <Text style={styles.memberEmail}>
                Joined {inv.accepted_at ? formatDate(inv.accepted_at) : '—'}
              </Text>
            </View>
          </View>
        ))}
      </View>

      {/* Invites section */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Invites</Text>

        {createdToken ? (
          <View style={styles.tokenBanner}>
            <Text style={styles.tokenBannerTitle}>Invite created</Text>
            <Text style={styles.tokenBannerHint}>
              Share this token with the invitee. Long-press to copy.
            </Text>
            <Text selectable style={styles.tokenText}>
              {createdToken}
            </Text>
            <Pressable
              onPress={() => setCreatedToken(null)}
              hitSlop={8}
              style={styles.tokenDismiss}
            >
              <Text style={styles.tokenDismissText}>Dismiss</Text>
            </Pressable>
          </View>
        ) : null}

        {canInvite ? (
          <View style={styles.inviteForm}>
            <TextInput
              label="Invite by email"
              placeholder="person@example.com"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="email"
              keyboardType="email-address"
              textContentType="emailAddress"
              value={inviteEmail}
              onChangeText={setInviteEmail}
            />
            <Button
              title="Send invite"
              onPress={handleSendInvite}
              loading={createInvite.isPending}
              disabled={!inviteEmail.trim()}
            />
          </View>
        ) : (
          <Text style={styles.bodyText}>
            Household is at the 2-member limit. Revoke or remove a member to
            invite someone else.
          </Text>
        )}

        <Text style={styles.subheader}>Pending</Text>
        {pendingInvites.isLoading ? (
          <LoadingSpinner />
        ) : pending.length === 0 ? (
          <EmptyState message="No pending invites." />
        ) : (
          pending.map((inv) => (
            <View key={inv.id} style={styles.inviteRow}>
              <View style={styles.inviteMain}>
                <Text style={styles.inviteEmail}>{inv.email}</Text>
                <Text style={styles.inviteMeta}>
                  Expires {formatDate(inv.expires_at)}
                </Text>
              </View>
              <Pressable
                onPress={() => handleRevoke(inv)}
                hitSlop={8}
                style={styles.revokeButton}
              >
                <Text style={styles.revokeText}>Revoke</Text>
              </Pressable>
            </View>
          ))
        )}
      </View>

      {/* Sign out */}
      <View style={styles.signOutWrap}>
        <Button
          title="Sign out"
          onPress={handleSignOut}
          variant="secondary"
        />
      </View>
    </KeyboardAwareScreen>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: spacing.lg,
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  cardTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  householdName: {
    fontSize: fontSize.xl,
    fontWeight: fontWeight.bold,
    color: colors.text,
    marginTop: spacing.xs,
  },
  metaText: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  bodyText: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  switchLabel: {
    fontSize: fontSize.md,
    color: colors.text,
  },
  fieldLabel: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  dayInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: fontSize.md,
    color: colors.text,
    backgroundColor: colors.background,
  },
  dayInputDisabled: {
    backgroundColor: colors.surface,
    color: colors.textTertiary,
  },
  saveButton: {
    marginTop: spacing.md,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
  },
  memberMain: {
    flex: 1,
  },
  memberName: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: colors.text,
  },
  memberEmail: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  memberMeta: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
  },
  tokenBanner: {
    backgroundColor: colors.successLight,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  tokenBannerTitle: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.success,
    marginBottom: spacing.xs,
  },
  tokenBannerHint: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  tokenText: {
    fontSize: fontSize.sm,
    fontFamily: 'monospace',
    color: colors.text,
    backgroundColor: colors.background,
    padding: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  tokenDismiss: {
    alignSelf: 'flex-end',
    marginTop: spacing.sm,
  },
  tokenDismissText: {
    fontSize: fontSize.xs,
    color: colors.primary,
  },
  inviteForm: {
    marginBottom: spacing.md,
  },
  subheader: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: colors.textSecondary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  inviteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
  },
  inviteMain: {
    flex: 1,
  },
  inviteEmail: {
    fontSize: fontSize.md,
    color: colors.text,
  },
  inviteMeta: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginTop: 2,
  },
  revokeButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  revokeText: {
    fontSize: fontSize.sm,
    color: colors.danger,
    fontWeight: fontWeight.medium,
  },
  signOutWrap: {
    marginTop: spacing.lg,
  },
  navRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  navMain: {
    flex: 1,
  },
  navChevron: {
    fontSize: fontSize.xxl,
    color: colors.textTertiary,
    marginLeft: spacing.md,
  },
});
