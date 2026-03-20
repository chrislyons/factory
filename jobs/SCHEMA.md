# Job ID Schema

## Format

```
job.##.###.####
```

Fixed 16-character identifier: `job.` prefix + domain (2 digits) + class (3 digits) + address (4 digits), dot-separated.

## Components

| Field   | Width | Description                                      | Governance    |
|---------|-------|--------------------------------------------------|---------------|
| Domain  | 2     | Agent routing prefix (e.g. `00` = System)        | Human-gated   |
| Class   | 3     | Work category (e.g. `001` = Infrastructure)      | Human-gated   |
| Address | 4     | Sequential item within domain+class pair         | Auto-increment|

## File Layout

```
jobs/
  registry.yaml              # Domain and class definitions
  SCHEMA.md                   # This file
  migration-map.yaml          # Legacy fct-### to job.## mapping
  00/                         # System domain
    job.00.001.0001.yaml
    job.00.001.0002.yaml
  10/                         # Boot domain
    job.10.002.0001.yaml
  ...
```

Each job file is a standalone YAML document at `jobs/<domain>/job.DD.CCC.AAAA.yaml`.

## Rules

- Domains and classes are human-gated decisions; new allocations require explicit approval.
- Addresses auto-increment per (domain, class) pair starting at `0001`.
- The `completed` block from the legacy system is eliminated; done items retain their real class.
- See `registry.yaml` for current domain and class allocations.
- See FCT015 for full architecture rationale.
