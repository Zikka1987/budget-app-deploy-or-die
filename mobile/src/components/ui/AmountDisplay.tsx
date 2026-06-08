import React from 'react';
import { StyleSheet, Text, TextStyle } from 'react-native';

import { colors, fontSize, fontWeight } from '@/theme/tokens';
import { formatDKK } from '@/lib/format';

interface AmountDisplayProps {
  amount: string | number;
  size?: 'sm' | 'md' | 'lg';
  color?: string;
  style?: TextStyle;
}

export function AmountDisplay({
  amount,
  size = 'md',
  color,
  style,
}: AmountDisplayProps) {
  return (
    <Text style={[styles.base, styles[size], color ? { color } : undefined, style]}>
      {formatDKK(amount)}
    </Text>
  );
}

const styles = StyleSheet.create({
  base: {
    fontWeight: fontWeight.semibold,
    color: colors.text,
    fontVariant: ['tabular-nums'],
  },
  sm: {
    fontSize: fontSize.sm,
  },
  md: {
    fontSize: fontSize.md,
  },
  lg: {
    fontSize: fontSize.xl,
  },
});
