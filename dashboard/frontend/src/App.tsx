import { NavLink, Outlet } from 'react-router-dom'
import { useTheme } from './theme'

export default function App() {
  const { theme, toggle } = useTheme()
  return (
    <div>
      <nav className="topnav">
        <span className="brand">VOLI Scorer Dashboard</span>
        <NavLink to="/history" className={({ isActive }) => (isActive ? 'active' : '')}>
          History
        </NavLink>
        <NavLink to="/new" className={({ isActive }) => (isActive ? 'active' : '')}>
          New Run
        </NavLink>
        <NavLink to="/builder" className={({ isActive }) => (isActive ? 'active' : '')}>
          Builder
        </NavLink>
        <NavLink to="/compare" className={({ isActive }) => (isActive ? 'active' : '')}>
          Compare
        </NavLink>
        <button
          className="theme-toggle"
          onClick={toggle}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label="Toggle color theme"
        >
          {theme === 'dark' ? '☀ light' : '🌙 dark'}
        </button>
      </nav>
      <main className="container">
        <Outlet />
      </main>
    </div>
  )
}
