import { Stack } from 'expo-router';

export default function BudgetLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Budget' }} />
      <Stack.Screen name="months" options={{ title: 'Budget Months' }} />
    </Stack>
  );
}
