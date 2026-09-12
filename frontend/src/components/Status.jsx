import React from 'react'

// The one loading / empty / error component every card uses. Never render a blank box.
export default function Status({ loading, error, empty, children, loadingText = 'Loading…', emptyText = 'Nothing to show yet.' }) {
  if (error) return <div className="status error">Could not load: {String(error)}</div>
  if (loading) return <div className="status"><span className="spinner" />{loadingText}</div>
  if (empty) return <div className="status empty">{emptyText}</div>
  return children || null
}

export function ChartBox({ loading, error, children, height, loadingText = 'Working…' }) {
  return (
    <div className="chart-wrap" style={{ minHeight: height }}>
      {children}
      {loading ? <div className="overlay"><span className="spinner" />{loadingText}</div> : null}
      {error ? <div className="overlay err">{String(error)}</div> : null}
    </div>
  )
}
