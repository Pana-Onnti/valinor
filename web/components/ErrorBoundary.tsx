'use client';
import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    this.props.onError?.(error);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <div className="text-2xl mb-2">⚠</div>
          <p className="font-semibold text-red-800">Error al cargar componente</p>
          <p className="text-sm text-red-600 mt-1">{this.state.error?.message}</p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-3 px-4 py-1.5 bg-red-100 hover:bg-red-200 rounded-lg text-red-700 text-sm"
          >
            Reintentar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
