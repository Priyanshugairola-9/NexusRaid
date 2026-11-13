import { useEffect, useState } from "react";

const NAV = [
  { group: null, items: [{ path: "/", label: "Overview" }] },
  { group: "Historical analysis", items: [
    { path: "/upload", label: "Upload dataset" },
    { path: "/datasets", label: "Datasets" },
    { path: "/reports", label: "Reports" },
  ] },
  { group: "Live", items: [{ path: "/monitoring", label: "Live monitoring" }] },
  { group: null, items: [{ path: "/settings", label: "Settings" }] },
];

function isCurrent(itemPath, routePath) {
  if (itemPath === "/") return routePath === "/";
  return routePath === itemPath || routePath.startsWith(`${itemPath}/`);
}

export function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="var(--accent)" />
      <path d="M6 22 L12 14 L17 18 L26 8" fill="none" stroke="var(--surface)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="26" cy="8" r="2.6" fill="var(--warn)" />
    </svg>
  );
}

export default function Layout({ route, theme, onToggleTheme, children }) {
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [route.path]);
  const routePath = route.parts[0] === "datasets" ? "/datasets" : route.path;
  return (
    <div className="app">
      <nav className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Main navigation">
        <div className="brand"><Logo /> NexusRaid</div>
        <div className="nav">
          {NAV.map((section, index) => (
            <div key={index}>
              {section.group && <div className="nav-group">{section.group}</div>}
              {section.items.map((item) => (
                <a key={item.path} href={`#${item.path}`} aria-current={isCurrent(item.path, routePath) ? "page" : undefined}>
                  {item.label}
                </a>
              ))}
            </div>
          ))}
        </div>
      </nav>
      <div className="main">
        <div className="topbar">
          <div className="row">
            <button className="btn small menu-button" onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen}>
              Menu
            </button>
            <span className="muted small topbar-note">Dataset analysis and early warning</span>
          </div>
          <button className="btn small" onClick={onToggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? "☀ Light theme" : "☾ Dark theme"}
          </button>
        </div>
        <main className="content" id="main">{children}</main>
      </div>
    </div>
  );
}
