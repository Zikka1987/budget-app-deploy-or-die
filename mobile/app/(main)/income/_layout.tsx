import { Stack } from 'expo-router';

export default function IncomeLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Income' }} />
      <Stack.Screen name="form" options={{ title: 'Income Entry' }} />
    </Stack>
  );
}
