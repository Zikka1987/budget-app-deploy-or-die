import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useSelectedMonth } from '@/contexts/month-context';
import { colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function formatMonthLabel(year: number, month: number): string {
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString('da-DK', { year: 'numeric', month: 'long' });
}

interface MonthSelectorProps {
  onMonthLabelPress?: () => void;
}

export function MonthSelector({ onMonthLabelPress }: MonthSelectorProps) {
  const { year, month, prevMonth, nextMonth } = useSelectedMonth();

  return (
    <View style={styles.container}>
      <Pressable onPress={prevMonth} style={styles.arrow}>
        <Text style={styles.arrowText}>{'\u2039'}</Text>
      </Pressable>
      <Pressable onPress={onMonthLabelPress} disabled={!onMonthLabelPress}>
        <Text style={styles.label}>{formatMonthLabel(year, month)}</Text>
      </Pressable>
      <Pressable onPress={nextMonth} style={styles.arrow}>
        <Text style={styles.arrowText}>{'\u203A'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.lg,
    gap: spacing.lg,
  },
  arrow: {
    padding: spacing.sm,
  },
  arrowText: {
    fontSize: fontSize.xxl,
    color: colors.primary,
    fontWeight: fontWeight.bold,
  },
  label: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: colors.text,
    textTransform: 'capitalize',
  },
});
