import type { PropsWithChildren, ReactNode } from "react";
import { DOC_LINKS, NAV_LINKS } from "../lib/constants";
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
  return (
    <div className="portal-app-shell">
      <header className="portal-header">
        <div className="portal-header__inner">
          <div>
            <a className="portal-brand" href="/">
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
            {statusSlot}
            <CommandPaletteButton />
          </div>
        </div>
      </header>

      <main className="portal-main">
        <section className="portal-hero">
          <div className="portal-hero__eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
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
  action
}: PropsWithChildren<{ title: string; subtitle?: string; action?: ReactNode }>) {
  return (
    <section className="surface-card">
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
