import { AppShell, SurfaceCard } from "../components/AppShell";
import { SyncClock } from "../components/primitives/SyncClock";
import type { ServiceHealth, SystemHealth } from "../lib/demo-data";
import { DEMO_SYSTEM_HEALTH } from "../lib/demo-data";
import { cn, relativeTimestamp } from "../lib/utils";

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

// ── Helpers ─────────────────────────────────────────────────────────

function statusIcon(status: ServiceHealth["status"]): string {
  switch (status) {
    case "up": return "●";
    case "down": return "○";
    case "degraded": return "◐";
    default: return "?";
  }
}

function statusTone(status: ServiceHealth["status"]): string {
  switch (status) {
    case "up": return "health-status--up";
    case "down": return "health-status--down";
    case "degraded": return "health-status--degraded";
    default: return "health-status--unknown";
  }
}

function categoryForService(name: string): string {
  if (name.startsWith("Inference")) return "Inference";
  if (name.startsWith("Hermes")) return "Gateways";
  if (name === "Matrix Bridge") return "Messaging";
  if (name === "Qdrant" || name === "Research MCP") return "Storage";
  if (name === "Portal (Caddy)") return "Proxy";
  if (name.startsWith("System")) return "System";
  return "Other";
}

// ── Service Row ─────────────────────────────────────────────────────

function ServiceRow({ service }: { service: ServiceHealth }) {
  return (
    <div className={cn("health-row", statusTone(service.status))}>
      <div className="health-row__status">
        <span className={cn("health-dot", `health-dot--${service.status}`)} />
      </div>
      <div className="health-row__info">
        <div className="health-row__name">{service.name}</div>
        {service.detail && <div className="health-row__detail">{service.detail}</div>}
      </div>
      <div className="health-row__meta">
        {service.latency_ms != null && (
          <span className={cn("health-latency", service.latency_ms > 500 && "health-latency--slow")}>
            {service.latency_ms}ms
          </span>
        )}
        <span className="health-row__time">{relativeTimestamp(service.last_check)}</span>
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export function HealthPage() {
  const data: SystemHealth = DEMO_MODE ? DEMO_SYSTEM_HEALTH : DEMO_SYSTEM_HEALTH;
  const updatedAt = new Date(data.checked_at).getTime();
  const upCount = data.services.filter((s) => s.status === "up").length;
  const degradedCount = data.services.filter((s) => s.status === "degraded").length;
  const downCount = data.services.filter((s) => s.status === "down").length;

  // Group by category
  const categories = new Map<string, ServiceHealth[]>();
  for (const s of data.services) {
    const cat = categoryForService(s.name);
    if (!categories.has(cat)) categories.set(cat, []);
    categories.get(cat)!.push(s);
  }

  return (
    <AppShell
      title="Health"
      description="System-wide service health and availability."
      pageKey="/pages/health.html"
      statusSlot={<SyncClock updatedAt={updatedAt} stale={false} />}
    >
      {/* Overall status */}
      <div className={cn("health-overall", `health-overall--${data.overall}`)}>
        <span className="health-overall__icon">
          {data.overall === "healthy" ? "✓" : data.overall === "degraded" ? "⚠" : "✗"}
        </span>
        <span className="health-overall__text">
          {data.overall === "healthy"
            ? "All systems operational"
            : data.overall === "degraded"
            ? "Some services degraded"
            : "Critical services down"}
        </span>
      </div>

      {/* Summary */}
      <div className="health-summary">
        <div className="health-summary__stat">
          <span className="health-summary__value health-summary__value--up">{upCount}</span>
          <span className="health-summary__label">Up</span>
        </div>
        {degradedCount > 0 && (
          <div className="health-summary__stat">
            <span className="health-summary__value health-summary__value--degraded">{degradedCount}</span>
            <span className="health-summary__label">Degraded</span>
          </div>
        )}
        {downCount > 0 && (
          <div className="health-summary__stat">
            <span className="health-summary__value health-summary__value--down">{downCount}</span>
            <span className="health-summary__label">Down</span>
          </div>
        )}
        <div className="health-summary__stat">
          <span className="health-summary__value">{data.services.length}</span>
          <span className="health-summary__label">Total</span>
        </div>
      </div>

      {/* Services by category */}
      {Array.from(categories.entries()).map(([category, services]) => (
        <SurfaceCard
          key={category}
          title={category}
          subtitle={`${services.filter((s) => s.status === "up").length}/${services.length} up`}
          className="surface-card--compact"
        >
          <div className="health-list">
            {services.map((s) => (
              <ServiceRow key={s.name} service={s} />
            ))}
          </div>
        </SurfaceCard>
      ))}
    </AppShell>
  );
}
