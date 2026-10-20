import { NavLink, Outlet } from 'react-router-dom'

export default function App() {
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
      </nav>
      <main className="container">
        <Outlet />
      </main>
    </div>
  )
}
