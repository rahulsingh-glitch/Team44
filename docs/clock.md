# Build-Day Clock — Team 44 (5 hours, one drill)

| Time | Phase | Focus |
|---|---|---|
| 0:00–0:20 | Kick-off & reveal | Read card; Rahul restates; Claude lists gaps; team decides answers |
| 0:20–1:00 | Architecture & backlog | Lock engine/idempotency/SCD2 (2 decisions w/ reasons); data model; CLAUDE.md; stories in Excel; infra green by 1:00 |
| 1:00–3:30 | Build, test, deploy | Bronze+silver → gold+marts → DQ+dashboard; DAG, CI, run-log/metrics; keep a working slice alive from hour 1 |
| 3:30–4:15 | SRE drill | Detect → triage (trimmed logs) → fix + regression test + alert → RCA |
| 4:15–4:45 | Demo & artifacts | 5-beat demo; all 10 artifacts in the shared folder |

**Protect 3:30–4:45.** The most common Track B failure is leaving SRE and the demo for the last ten minutes.

## Five-minute demo beats
1. Problem in one sentence (0:20)
2. Architecture + the key decision (0:40)
3. Live happy path — run DAG, show gold + dashboard (1:30)
4. A failure handled well — planted defect skipped / SCD2 history (1:00)
5. Metrics, the drill, the RCA (1:30)
