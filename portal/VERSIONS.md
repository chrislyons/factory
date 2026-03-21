# Factory Portal — Version Registry

**Repo:** `~/dev/factory/portal/` | **Host:** Blackbox (100.87.53.109) staging, Whitebox (future production)

---

## Deployed Versions

| Version | Commit | Date | Port | Status | Notes |
|---------|--------|------|------|--------|-------|
| v5 | — | 2026-03 | — | Retired | GSD-era vanilla JS dashboard |
| v6 | — | 2026-03-17 | — | Retired | First React port |
| v7 | — | 2026-03-17 | — | Retired | Pre-indigo palette |
| v8 | eebcb83 | 2026-03-20 | :41910 | Retired | Indigo palette, Geist Pixel Grid + Geist Mono, dark+light mode |
| v9 | 875f1b9 | 2026-03-21 | :41910 | Retired | Tab restructure: 5 tabs, SyncClock, mobile dropdown nav, merged pages, Objects page (334 items) |
| v9.1 | — | 2026-03-21 | :41910 | Live | Mobile optimization: shell 1400px/92vw, page titles (Jobs Tracker/Object Index/System Topology), Loop Controls redesign, job card mobile polish, agent detail compact cards, iOS zoom fix, overflow fixes |

---

## Port Scheme

All Factory services use the `:419xx` range. Ranges are grouped by function with room for growth.

| Range | Purpose | Capacity |
|-------|---------|----------|
| :41910-41919 | Production (live portal + backends) | 10 ports |
| :41920-41939 | Preview / version comparison slots | 20 ports |
| :41940-41949 | Development (hot-reload, experiments) | 10 ports |
| :41950-41959 | Coordinator (HTTP API, metrics, debug) | 10 ports |
| :41960-41969 | Reserved (future services) | 10 ports |

### Production (:41910-41919)

| Port | Service | Binding | Notes |
|------|---------|---------|-------|
| :41910 | Caddy portal (live) | 0.0.0.0 | Always latest deployed version |
| :41911 | GSD sidecar (server.py) | 127.0.0.1 | Task/status JSON backend |
| :41912 | (available) | — | Future portal sidecar |
| :41913-41919 | (available) | — | |

### Preview (:41920-41939)

| Port | Service | Notes |
|------|---------|-------|
| :41920 | Version slot A | Spin up any historical version for comparison |
| :41921 | Version slot B | Side-by-side compare |
| :41922-41939 | (available) | Build prototype previews during active dev |

### Coordinator (:41950-41959)

| Port | Service | Notes |
|------|---------|-------|
| :41950 | Coordinator-rs HTTP API | FCT-064 (future) |
| :41951 | Coordinator metrics | Prometheus-style (future) |
| :41952-41959 | (available) | Debug endpoints, admin |

---

## Migration Notes

- Blackbox (RP5, 100.87.53.109) is staging. Same port scheme transfers to Whitebox.
- Old ports (:41933, :41944, :41966, :41977, :41988) are retired as of 2026-03-20.
- Port defaults live in `serve.sh` and `.env` on the deployment host.

---

*Factory — Boot Industries — 2026-03-20*
