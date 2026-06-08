import { Tabs } from 'expo-router';

import { MonthProvider } from '@/contexts/month-context';
import { colors } from '@/theme/tokens';

export default function MainLayout() {
  return (
    <MonthProvider>
      <Tabs
        screenOptions={{
          tabBarActiveTintColor: colors.primary,
          tabBarInactiveTintColor: colors.textTertiary,
          headerShown: true,
        }}
      >
        <Tabs.Screen
          name="index"
          options={{
            title: 'Dashboard',
            tabBarLabel: 'Home',
          }}
        />
        <Tabs.Screen
          name="budget"
          options={{
            title: 'Budget',
            tabBarLabel: 'Budget',
            headerShown: false,
          }}
        />
        <Tabs.Screen
          name="income"
          options={{
            title: 'Income',
            tabBarLabel: 'Income',
            headerShown: false,
          }}
        />
        <Tabs.Screen
          name="savings"
          options={{
            title: 'Savings',
            tabBarLabel: 'Savings',
            headerShown: false,
          }}
        />
        <Tabs.Screen
          name="receipts"
          options={{
            title: 'Receipts',
            tabBarLabel: 'Receipts',
            headerShown: false,
          }}
        />
        <Tabs.Screen
          name="search"
          options={{
            title: 'Search',
            tabBarLabel: 'Search',
            headerShown: false,
          }}
        />
        <Tabs.Screen
          name="settings"
          options={{
            title: 'Settings',
            tabBarLabel: 'Settings',
            headerShown: false,
          }}
        />
      </Tabs>
    </MonthProvider>
  );
}
