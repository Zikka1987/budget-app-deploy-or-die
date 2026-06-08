import { Stack } from 'expo-router';

export default function ReceiptsLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Receipts' }} />
      <Stack.Screen name="upload" options={{ title: 'Upload Receipt' }} />
      <Stack.Screen name="manual" options={{ title: 'Manual Expense' }} />
      <Stack.Screen name="[id]" options={{ title: 'Receipt' }} />
    </Stack>
  );
}
