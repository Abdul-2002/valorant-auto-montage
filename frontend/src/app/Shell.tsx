import { NavLink, Outlet } from "react-router-dom";

export function Shell() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">LOST SI STUDIO</div>
        <nav className="nav">
          <NavLink to="/" end>
            Projects
          </NavLink>
          <NavLink to="/upload">Upload</NavLink>
          <NavLink to="/logs">Logs</NavLink>
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
            API
          </a>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
