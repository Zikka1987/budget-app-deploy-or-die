import { Stack } from 'expo-router';

export default function SavingsLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Savings' }} />
      <Stack.Screen name="rule-form" options={{ title: 'Savings Rule' }} />
      <Stack.Screen name="manual" options={{ title: 'Manual Savings' }} />
    </Stack>
  );
}
