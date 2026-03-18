import type { ReactNode } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";

export function PlaceholderPage({
  title,
  description,
  pageKey,
  sections
}: {
  title: string;
  description: string;
  pageKey: string;
  sections: Array<{ title: string; body: ReactNode }>;
}) {
  return (
    <AppShell title={title} description={description} pageKey={pageKey}>
      <div className="stack">
        {sections.map((section) => (
          <SurfaceCard key={section.title} title={section.title}>
            <div className="placeholder-copy">{section.body}</div>
          </SurfaceCard>
        ))}
      </div>
    </AppShell>
  );
}
