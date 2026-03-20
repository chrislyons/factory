import { useEffect } from "react";
import type { PropsWithChildren, ReactNode } from "react";
import { DOC_LINKS, NAV_LINKS, PORTAL_HOME } from "../lib/constants";
import { useTheme } from "../hooks/useTheme";
import { cn } from "../lib/utils";
import { CommandPaletteButton } from "./CommandPalette";

interface AppShellProps {
  title: string;
  eyebrow?: string;
  description?: string;
  statusSlot?: ReactNode;
  pageKey?: string;
}

export function AppShell({
  title,
  eyebrow = "Factory Portal",
  description,
  statusSlot,
  pageKey,
  children
}: PropsWithChildren<AppShellProps>) {
  const { theme, toggle } = useTheme();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === "\\") {
        e.preventDefault();
        toggle();
        return;
      }

      const idx = parseInt(e.key, 10) - 1;
      if (idx >= 0 && idx < NAV_LINKS.length) {
        e.preventDefault();
        window.location.href = NAV_LINKS[idx].href;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggle]);

  return (
    <div className="portal-app-shell">
      <header className="portal-header">
        <div className="portal-header__inner">
          <div>
            <a className="portal-brand" href={PORTAL_HOME}>
              <span className="portal-brand__title">factory</span>
              <span className="portal-brand__sub">portal</span>
            </a>
          </div>
          <nav className="portal-nav" aria-label="Operator navigation">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                className={cn("portal-nav__link", pageKey === link.href && "is-active")}
                href={link.href}
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="portal-header__actions">
            <button className="theme-toggle" type="button" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? "\u263E" : "\u2600"}
            </button>
            {statusSlot}
            <CommandPaletteButton />
          </div>
        </div>
      </header>

      <main className="portal-main">
        <section className="portal-hero">
          <div className="portal-hero__eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
        </section>
        <div className="portal-page-content">{children}</div>
      </main>

      <footer className="portal-footer">
        <div className="portal-footer__inner">
          <div>Paperclip-informed operator surface for Factory.</div>
          <div className="portal-footer__links">
            {DOC_LINKS.map((doc) => (
              <a key={doc.href} href={doc.href}>
                {doc.label}
              </a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}

export function SurfaceCard({
  title,
  subtitle,
  children,
  action,
  className
}: PropsWithChildren<{ title: string; subtitle?: string; action?: ReactNode; className?: string }>) {
  return (
    <section className={cn("surface-card", className)}>
      <div className="surface-card__header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
