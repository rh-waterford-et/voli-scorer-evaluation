import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import History from './views/History'
import NewRun from './views/NewRun'
import RunView from './views/RunView'
import Compare from './views/Compare'
import Builder from './views/Builder'
import { ThemeProvider } from './theme'
import ErrorBoundary from './components/ErrorBoundary'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />}>
            <Route index element={<Navigate to="/history" replace />} />
            <Route path="history" element={<History />} />
            <Route path="new" element={<NewRun />} />
            <Route path="builder" element={<Builder />} />
            <Route path="runs/:id" element={<RunView />} />
            <Route path="compare" element={<Compare />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
