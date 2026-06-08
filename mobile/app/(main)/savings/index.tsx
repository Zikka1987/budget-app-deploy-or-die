import React, { useState } from 'react';
import {
  Alert,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { useBudgetMonths } from '@/api/budgets';
import {
  useApproveProposal,
  useGenerateProposals,
  useRejectProposal,
  useSavingsProposals,
  useSavingsRules,
  useUpdateSavingsRule,
} from '@/api/savings';
import { useSelectedMonth } from '@/contexts/month-context';
import { MonthSelector } from '@/components/MonthSelector';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatDKK } from '@/lib/format';
import type {
  ProposalStatus,
  SavingsProposalResponse,
  SavingsRuleResponse,
} from '@/types/api';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

type Segment = 'rules' | 'proposals';

export default function SavingsScreen() {
  const [segment, setSegment] = useState<Segment>('rules');
  const [approveTarget, setApproveTarget] = useState<SavingsProposalResponse | null>(
    null,
  );
  const [approveAmount, setApproveAmount] = useState('');

  const { year, month } = useSelectedMonth();
  const monthStr = `${year}-${String(month).padStart(2, '0')}-01`;
  const { data: monthsData } = useBudgetMonths();
  const budgetMonth = monthsData?.months.find((m) => m.month === monthStr);
  const budgetMonthId = budgetMonth?.id;

  const rulesQuery = useSavingsRules();
  const proposalsQuery = useSavingsProposals(budgetMonthId);
  const updateRule = useUpdateSavingsRule();
  const generateProposals = useGenerateProposals();
  const approveProposal = useApproveProposal();
  const rejectProposal = useRejectProposal();

  const handleAddRule = () => router.push('/(main)/savings/rule-form');
  const handleEditRule = (rule: SavingsRuleResponse) =>
    router.push({
      pathname: '/(main)/savings/rule-form',
      params: { ruleId: rule.id },
    });
  const handleManualEntry = () => router.push('/(main)/savings/manual');

  const handleToggleActive = (rule: SavingsRuleResponse, value: boolean) => {
    updateRule.mutate(
      { ruleId: rule.id, data: { is_active: value } },
      { onError: (err) => Alert.alert('Error', err.message) },
    );
  };

  const handleGenerate = () => {
    if (!budgetMonthId) return;
    generateProposals.mutate(budgetMonthId, {
      onError: (err) => Alert.alert('Error', err.message),
    });
  };

  const openApproveModal = (proposal: SavingsProposalResponse) => {
    setApproveTarget(proposal);
    setApproveAmount(String(proposal.proposed_amount));
  };

  const closeApproveModal = () => {
    setApproveTarget(null);
    setApproveAmount('');
  };

  const handleConfirmApprove = () => {
    if (!approveTarget) return;
    const parsed = parseFloat(approveAmount.trim());
    if (isNaN(parsed) || parsed <= 0) {
      Alert.alert('Validation', 'Final amount must be a positive number.');
      return;
    }
    approveProposal.mutate(
      { proposalId: approveTarget.id, finalAmount: parsed },
      {
        onSuccess: closeApproveModal,
        onError: (err) => Alert.alert('Error', err.message),
      },
    );
  };

  const handleReject = (proposal: SavingsProposalResponse) => {
    Alert.alert(
      'Reject Proposal',
      `Reject "${proposal.rule_label}" of ${formatDKK(proposal.proposed_amount)}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reject',
          style: 'destructive',
          onPress: () =>
            rejectProposal.mutate(proposal.id, {
              onError: (err) => Alert.alert('Error', err.message),
            }),
        },
      ],
    );
  };

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Button
          title="Manual Savings Entry"
          variant="secondary"
          onPress={handleManualEntry}
          style={styles.manualButton}
        />

        <View style={styles.segmentRow}>
          <Pressable
            style={[
              styles.segmentPill,
              segment === 'rules' && styles.segmentPillActive,
            ]}
            onPress={() => setSegment('rules')}
          >
            <Text
              style={[
                styles.segmentText,
                segment === 'rules' && styles.segmentTextActive,
              ]}
            >
              Rules
            </Text>
          </Pressable>
          <Pressable
            style={[
              styles.segmentPill,
              segment === 'proposals' && styles.segmentPillActive,
            ]}
            onPress={() => setSegment('proposals')}
          >
            <Text
              style={[
                styles.segmentText,
                segment === 'proposals' && styles.segmentTextActive,
              ]}
            >
              Proposals
            </Text>
          </Pressable>
        </View>

        {segment === 'rules' ? (
          <RulesSegment
            rules={rulesQuery.data?.rules ?? []}
            isLoading={rulesQuery.isLoading}
            onAdd={handleAddRule}
            onEdit={handleEditRule}
            onToggleActive={handleToggleActive}
          />
        ) : (
          <ProposalsSegment
            budgetMonthId={budgetMonthId}
            proposals={proposalsQuery.data?.proposals ?? []}
            isLoading={proposalsQuery.isLoading}
            isGenerating={generateProposals.isPending}
            onGenerate={handleGenerate}
            onApprove={openApproveModal}
            onReject={handleReject}
          />
        )}
      </ScrollView>

      <ApproveModal
        proposal={approveTarget}
        amount={approveAmount}
        onAmountChange={setApproveAmount}
        onConfirm={handleConfirmApprove}
        onCancel={closeApproveModal}
        isPending={approveProposal.isPending}
      />
    </View>
  );
}

interface RulesSegmentProps {
  rules: SavingsRuleResponse[];
  isLoading: boolean;
  onAdd: () => void;
  onEdit: (rule: SavingsRuleResponse) => void;
  onToggleActive: (rule: SavingsRuleResponse, value: boolean) => void;
}

function RulesSegment({
  rules,
  isLoading,
  onAdd,
  onEdit,
  onToggleActive,
}: RulesSegmentProps) {
  if (isLoading) return <LoadingSpinner />;

  return (
    <View>
      <Button title="Add Rule" onPress={onAdd} style={styles.addButton} />
      {rules.length === 0 ? (
        <EmptyState message="No savings rules yet." />
      ) : (
        rules.map((rule) => (
          <Pressable
            key={rule.id}
            style={styles.ruleRow}
            onPress={() => onEdit(rule)}
          >
            <View style={styles.ruleLeft}>
              <Text style={styles.ruleLabel}>{rule.label}</Text>
              <Text style={styles.ruleCategory}>{rule.category_name}</Text>
              <Text style={styles.ruleType}>{formatRuleType(rule)}</Text>
            </View>
            <View style={styles.ruleRight}>
              <Switch
                value={rule.is_active}
                onValueChange={(v) => onToggleActive(rule, v)}
              />
            </View>
          </Pressable>
        ))
      )}
    </View>
  );
}

interface ProposalsSegmentProps {
  budgetMonthId?: string;
  proposals: SavingsProposalResponse[];
  isLoading: boolean;
  isGenerating: boolean;
  onGenerate: () => void;
  onApprove: (proposal: SavingsProposalResponse) => void;
  onReject: (proposal: SavingsProposalResponse) => void;
}

function ProposalsSegment({
  budgetMonthId,
  proposals,
  isLoading,
  isGenerating,
  onGenerate,
  onApprove,
  onReject,
}: ProposalsSegmentProps) {
  return (
    <View>
      <MonthSelector />
      {!budgetMonthId ? (
        <EmptyState message="No budget month for this period. Initialize it from the Budget tab." />
      ) : (
        <>
          <Button
            title="Generate Proposals"
            onPress={onGenerate}
            loading={isGenerating}
            style={styles.addButton}
          />
          {isLoading ? (
            <LoadingSpinner />
          ) : proposals.length === 0 ? (
            <EmptyState message="No proposals for this month. Tap Generate to create them from your active rules." />
          ) : (
            proposals.map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                onApprove={onApprove}
                onReject={onReject}
              />
            ))
          )}
        </>
      )}
    </View>
  );
}

interface ProposalCardProps {
  proposal: SavingsProposalResponse;
  onApprove: (proposal: SavingsProposalResponse) => void;
  onReject: (proposal: SavingsProposalResponse) => void;
}

function ProposalCard({ proposal, onApprove, onReject }: ProposalCardProps) {
  const isPending = proposal.status === 'pending';
  const showBoth =
    proposal.status === 'posted' &&
    proposal.final_amount !== null &&
    proposal.final_amount !== proposal.proposed_amount;

  return (
    <View style={styles.proposalCard}>
      <View style={styles.proposalHeader}>
        <Text style={styles.proposalLabel}>{proposal.rule_label}</Text>
        <StatusBadge status={proposal.status} />
      </View>
      <Text style={styles.proposalAmount}>
        {formatDKK(proposal.proposed_amount)}
        {showBoth ? ` → ${formatDKK(proposal.final_amount!)}` : ''}
      </Text>
      {isPending && (
        <View style={styles.proposalActions}>
          <Button
            title="Approve"
            onPress={() => onApprove(proposal)}
            style={styles.actionButton}
          />
          <Button
            title="Reject"
            variant="secondary"
            onPress={() => onReject(proposal)}
            style={styles.actionButton}
          />
        </View>
      )}
    </View>
  );
}

function StatusBadge({ status }: { status: ProposalStatus }) {
  const { bg, fg, label } = badgeStyles(status);
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{label}</Text>
    </View>
  );
}

function badgeStyles(status: ProposalStatus): { bg: string; fg: string; label: string } {
  switch (status) {
    case 'pending':
      return { bg: colors.warningLight, fg: colors.warning, label: 'Pending' };
    case 'posted':
      return { bg: colors.successLight, fg: colors.success, label: 'Posted' };
    case 'rejected':
      return { bg: colors.surface, fg: colors.textTertiary, label: 'Rejected' };
  }
}

function formatRuleType(rule: SavingsRuleResponse): string {
  if (rule.rule_type === 'percent_of_income' && rule.percent_value !== null) {
    return `${rule.percent_value}% of income`;
  }
  if (rule.rule_type === 'fixed_monthly' && rule.fixed_amount !== null) {
    return `${formatDKK(rule.fixed_amount)} / month`;
  }
  return '';
}

interface ApproveModalProps {
  proposal: SavingsProposalResponse | null;
  amount: string;
  onAmountChange: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}

function ApproveModal({
  proposal,
  amount,
  onAmountChange,
  onConfirm,
  onCancel,
  isPending,
}: ApproveModalProps) {
  return (
    <Modal
      visible={!!proposal}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
    >
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.modalTitle}>Approve Proposal</Text>
          {proposal && (
            <>
              <Text style={styles.modalLabel}>{proposal.rule_label}</Text>
              <Text style={styles.modalProposed}>
                Proposed: {formatDKK(proposal.proposed_amount)}
              </Text>
              <TextInput
                label="Final amount (kr.)"
                value={amount}
                onChangeText={onAmountChange}
                keyboardType="numeric"
              />
              <View style={styles.modalActions}>
                <Button
                  title="Cancel"
                  variant="secondary"
                  onPress={onCancel}
                  style={styles.actionButton}
                />
                <Button
                  title="Confirm"
                  onPress={onConfirm}
                  loading={isPending}
                  style={styles.actionButton}
                />
              </View>
            </>
          )}
        </View>
      </View>
    </Modal>
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
  manualButton: {
    marginBottom: spacing.lg,
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
  addButton: {
    marginBottom: spacing.lg,
  },
  ruleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.xs,
  },
  ruleLeft: {
    flex: 1,
    marginRight: spacing.md,
  },
  ruleLabel: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: colors.text,
  },
  ruleCategory: {
    fontSize: fontSize.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  ruleType: {
    fontSize: fontSize.xs,
    color: colors.textTertiary,
    marginTop: 2,
  },
  ruleRight: {
    alignItems: 'flex-end',
  },
  proposalCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  proposalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  proposalLabel: {
    flex: 1,
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginRight: spacing.sm,
  },
  proposalAmount: {
    fontSize: fontSize.sm,
    color: colors.text,
    fontVariant: ['tabular-nums'],
    marginBottom: spacing.sm,
  },
  proposalActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  actionButton: {
    flex: 1,
  },
  badge: {
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.full,
  },
  badgeText: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
  },
  modalCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    padding: spacing.xl,
  },
  modalTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    marginBottom: spacing.md,
  },
  modalLabel: {
    fontSize: fontSize.md,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  modalProposed: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  modalActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
});
