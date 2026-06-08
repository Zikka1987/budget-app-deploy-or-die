import React from 'react';

import { ErrorView } from './ui/ErrorView';
import { logError } from '@/lib/errorLog';

type Props = { children: React.ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    logError('boundary', error, { componentStack: info.componentStack });
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return <ErrorView error={this.state.error} onRetry={this.reset} />;
    }
    return this.props.children;
  }
}
