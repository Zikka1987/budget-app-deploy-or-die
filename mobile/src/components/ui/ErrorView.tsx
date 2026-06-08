import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/lib/api-client';
import { colors, fontSize, spacing } from '@/theme/tokens';
import { Button } from './Button';

interface ErrorViewProps {
  message?: string;
  error?: unknown;
  onRetry?: () => void;
}

function friendlyMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return 'Connection problem. Check your network and try again.';
    }
    if (error.status === 401) {
      return 'Your session has expired. Please sign in again.';
    }
    if (error.status >= 500) {
      return 'The server is having trouble right now. Please try again shortly.';
    }
    return error.detail ?? error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Something went wrong.';
}

export function ErrorView({ message, error, onRetry }: ErrorViewProps) {
  const text = message ?? friendlyMessage(error);
  return (
    <View style={styles.container}>
      <Text style={styles.text}>{text}</Text>
      {onRetry && (
        <Button
          title="Try again"
          onPress={onRetry}
          variant="secondary"
          style={styles.button}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
    backgroundColor: colors.background,
  },
  text: {
    fontSize: fontSize.md,
    color: colors.textSecondary,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
  button: {
    minWidth: 120,
  },
});
