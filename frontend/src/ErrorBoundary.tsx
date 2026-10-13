import React from 'react'

interface State { error: Error | null }

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 48, textAlign: 'center', fontFamily: 'monospace' }}>
          <h2 style={{ marginBottom: 12 }}>Something went wrong</h2>
          <pre style={{ fontSize: '0.8rem', opacity: 0.6, marginBottom: 20, whiteSpace: 'pre-wrap' }}>
            {this.state.error.message}
          </pre>
          <button onClick={() => this.setState({ error: null })}>Retry</button>
        </div>
      )
    }
    return this.props.children
  }
}
