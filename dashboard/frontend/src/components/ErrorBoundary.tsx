import React from 'react'

interface State {
  error: Error | null
}

// Renders a readable error page instead of a blank screen when a view
// crashes, so the failure is diagnosable without opening dev tools first.
export default class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('dashboard view crashed:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="container">
          <div className="error-text panel">
            <strong>Something broke in the dashboard UI.</strong>
            <pre className="log" style={{ marginTop: 10 }}>
              {this.state.error.toString()}
            </pre>
            <p className="muted">
              Check the browser console for the stack trace, then reload. Stored run data is
              unaffected — History and the backend keep working.
            </p>
            <button className="primary" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
