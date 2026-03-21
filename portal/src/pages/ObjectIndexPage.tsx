import { AppShell } from "../components/AppShell";
import { ObjectIndexContent } from "../components/ObjectIndexContent";

export function ObjectIndexPage() {
  return (
    <AppShell title="Object Index" pageKey="/pages/docs.html?tab=objects">
      <ObjectIndexContent />
    </AppShell>
  );
}
