import React, { useEffect, useState } from 'react';
import { AppState, type AppStateStatus, Platform } from 'react-native';
import {
  Slot,
  usePathname,
  useRouter,
  useNavigationContainerRef,
} from 'expo-router';
import {
  focusManager,
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';

import { AuthProvider, useAuth } from '@/contexts/auth-context';
import { useOnboardingStatus } from '@/api/onboarding';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { ErrorView } from '@/components/ui/ErrorView';
import { logError } from '@/lib/errorLog';

// Expo Router v6 `usePathname()` strips route-group segments (parens-wrapped
// folders), so `app/(auth)/sign-in.tsx` reports as `/sign-in`, etc. Verified
// against the installed expo-router source (build/global-state/routeInfo.js).

// Auth routes that an unauthenticated user is allowed to remain on. Without
// this, navigating sign-in → sign-up bounces back to sign-in because the gate
// re-evaluates after the route change.
const AUTH_ALLOWED = new Set<string>([
  '/sign-in',
  '/sign-up',
]);

// Pre-household routes that an authenticated-but-pre-household user is allowed
// to remain on (otherwise they'd be redirected back to create-household).
const PRE_HOUSEHOLD_ALLOWED = new Set<string>([
  '/create-household',
  '/accept-invite',
]);

// Routes that a fully-onboarded user should be moved off (back to main).
// Required because the auth and onboarding flows themselves don't navigate —
// RootGate is what kicks the user into (main) after sign-in or after the
// last onboarding step completes. Without this gating, the gate's final
// branch fires on EVERY render inside (main), hijacking tab navigation by
// redirecting the user back to the group's default screen (Home).
const REDIRECT_TO_MAIN_FROM = new Set<string>([
  '/sign-in',
  '/sign-up',
  '/create-household',
  '/accept-invite',
  '/categories',
  '/initialize-month',
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
      // refetchOnReconnect intentionally NOT set — without
      // @react-native-community/netinfo wiring on `onlineManager`, the flag is a
      // no-op in React Native. Adding netinfo is a separate native-dep decision;
      // this hardening pass does not assert reconnect behavior.
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) =>
      logError('query', error, { key: query.queryKey }),
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) =>
      logError('mutation', error, { key: mutation.options.mutationKey }),
  }),
});

// Bridge React Native AppState → React Query focusManager so
// `refetchOnWindowFocus: true` actually fires when the app returns to the
// foreground. Without this, the flag is a silent no-op in React Native.
focusManager.setEventListener((handleFocus) => {
  const subscription = AppState.addEventListener(
    'change',
    (status: AppStateStatus) => {
      if (Platform.OS !== 'web') handleFocus(status === 'active');
    },
  );
  return () => subscription.remove();
});

function RootGate() {
  const { session, isLoading: authLoading } = useAuth();
  const hasSession = !!session;
  const pathname = usePathname();
  const router = useRouter();
  const navigationRef = useNavigationContainerRef();
  const [isNavReady, setIsNavReady] = useState(() => navigationRef.isReady());

  // router.replace() throws assertIsReady if navigation isn't mounted yet
  // (verified: node_modules/expo-router/build/global-state/routing.js:62-66).
  // On cold start the routing useEffect below can fire before navigation is
  // ready; without this gate the throw is silently logged and routing dies
  // with no recovery — the user is stuck on /sign-in until any user-driven
  // navigation event happens to be ready and re-fires the routing useEffect.
  // Subscribe to the navigation container's `state` event (the canonical
  // readiness signal) and flip a flag once it's ready.
  useEffect(() => {
    if (isNavReady) return;
    if (navigationRef.isReady()) {
      setIsNavReady(true);
      return;
    }
    const unsub = navigationRef.addListener('state', () => {
      if (navigationRef.isReady()) setIsNavReady(true);
    });
    return unsub;
  }, [navigationRef, isNavReady]);

  const {
    data: onboarding,
    isLoading: onboardingLoading,
    error: onboardingError,
    refetch: retryOnboarding,
  } = useOnboardingStatus(hasSession);

  // Imperative routing via `router.replace` from a useEffect. Prior to this
  // we returned `<Redirect>` components; that uses `useFocusEffect` under the
  // hood, which can silently no-op when emitted from a sibling-of-Slot
  // component in response to a state change (e.g. session hydration after
  // reload), because the focused navigation context isn't re-evaluated.
  // useEffect fires deterministically when its deps change, so every routing
  // decision now happens reliably.
  useEffect(() => {
    if (!isNavReady) return;
    if (authLoading) return;

    if (!session) {
      if (!AUTH_ALLOWED.has(pathname)) {
        router.replace('/(auth)/sign-in');
      }
      return;
    }

    if (onboardingLoading || onboardingError) return;

    if (!onboarding?.has_household) {
      if (!PRE_HOUSEHOLD_ALLOWED.has(pathname)) {
        router.replace('/(onboarding)/create-household');
      }
      return;
    }

    const allCategoriesReady =
      onboarding.has_income_category &&
      onboarding.has_expense_category &&
      onboarding.has_savings_category;
    if (!allCategoriesReady) {
      if (pathname !== '/categories') {
        router.replace('/(onboarding)/categories');
      }
      return;
    }

    if (REDIRECT_TO_MAIN_FROM.has(pathname)) {
      router.replace('/(main)');
    }
  }, [
    isNavReady,
    authLoading,
    session,
    pathname,
    onboarding,
    onboardingLoading,
    onboardingError,
    router,
  ]);

  if (authLoading) return <LoadingSpinner />;
  if (session && onboardingLoading && !onboarding) return <LoadingSpinner />;
  if (onboardingError) {
    return (
      <ErrorView
        message="Could not load your account status. Check your connection and try again."
        onRetry={() => retryOnboarding()}
      />
    );
  }
  return null;
}

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ErrorBoundary>
          <RootGate />
          <Slot />
        </ErrorBoundary>
      </AuthProvider>
    </QueryClientProvider>
  );
}
