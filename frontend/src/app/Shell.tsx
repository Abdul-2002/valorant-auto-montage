import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ActiveRunStrip } from "../ui/ActiveRunStrip";

/** Job workspace routes where chrome must stay out of the way of the preview. */
function isWorkspacePath(pathname: string): boolean {
  return /\/jobs\/[^/]+\/(edit|review|render|select)(?:\/|$)/.test(pathname);
}

/** Hub pages where the run strip and always-on brand bar are useful. */
function isHubPath(pathname: string): boolean {
  return pathname === "/" || pathname.startsWith("/upload") || pathname.startsWith("/logs");
}

export function Shell() {
  const location = useLocation();
  const workspace = isWorkspacePath(location.pathname);
  const hub = isHubPath(location.pathname);
  const [chromeHidden, setChromeHidden] = useState(workspace);

  useEffect(() => {
    // Entering the editor: hide brand bar so preview gets the viewport.
    setChromeHidden(workspace);
  }, [workspace, location.pathname]);

  useEffect(() => {
    if (!workspace) return;

    let lastY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      if (y < 8) {
        setChromeHidden(false);
      } else if (y > lastY + 4) {
        setChromeHidden(true);
      } else if (y < lastY - 4) {
        setChromeHidden(false);
      }
      lastY = y;
    };

    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -6) setChromeHidden(false);
      if (e.deltaY > 6) setChromeHidden(true);
    };

    const onMove = (e: MouseEvent) => {
      if (e.clientY <= 10) setChromeHidden(false);
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("mousemove", onMove);
    };
  }, [workspace]);

  return (
    <div className={`shell ${workspace ? "shell-workspace" : ""} ${chromeHidden ? "shell-chrome-hidden" : ""}`}>
      <header className={`topbar ${chromeHidden ? "topbar-away" : ""}`} aria-hidden={chromeHidden}>
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
      {hub ? <ActiveRunStrip /> : null}
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
