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

    /** Auto-hide delay after edge-peek so studio toolbar stays usable. */
    const HIDE_MS = 4500;
    /** Leave the top strip before auto-hide can fire. */
    const LEAVE_Y = 56;
    let hideTimer: ReturnType<typeof setTimeout> | null = null;
    let lastY = window.scrollY;

    const clearHideTimer = () => {
      if (hideTimer !== null) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
    };

    const scheduleHide = () => {
      clearHideTimer();
      hideTimer = setTimeout(() => setChromeHidden(true), HIDE_MS);
    };

    const reveal = () => {
      setChromeHidden(false);
      scheduleHide();
    };

    const onScroll = () => {
      const y = window.scrollY;
      if (y < 8) {
        reveal();
      } else if (y > lastY + 4) {
        clearHideTimer();
        setChromeHidden(true);
      } else if (y < lastY - 4) {
        reveal();
      }
      lastY = y;
    };

    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -6) reveal();
      if (e.deltaY > 6) {
        clearHideTimer();
        setChromeHidden(true);
      }
    };

    const onMove = (e: MouseEvent) => {
      if (e.clientY <= 10) {
        reveal();
        return;
      }
      // Cursor left the top strip — hide on schedule (do not cancel if already open).
      if (e.clientY > LEAVE_Y && hideTimer === null) {
        scheduleHide();
      }
    };

    const onTopbarEnter = () => clearHideTimer();
    const onTopbarLeave = () => scheduleHide();

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("mousemove", onMove, { passive: true });
    const bar = document.querySelector(".shell-workspace .topbar");
    bar?.addEventListener("mouseenter", onTopbarEnter);
    bar?.addEventListener("mouseleave", onTopbarLeave);
    return () => {
      clearHideTimer();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("mousemove", onMove);
      bar?.removeEventListener("mouseenter", onTopbarEnter);
      bar?.removeEventListener("mouseleave", onTopbarLeave);
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
