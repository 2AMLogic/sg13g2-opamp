# spec/

Target specification and decision records. Spec changes require a decision record.

- [`target-spec.md`](target-spec.md) — the ratified target-spec table (rows, bounds, value tags).
- [`consumers.md`](consumers.md) — who declares `consumes: sg13g2-opamp`, the requirement rows each
  consumer imposes, and per-row verdicts against the ratified spec (2am cross-cutting rule 9).
- [`integrator.json`](integrator.json) — the machine-readable integrator view at this fixed path:
  top cell, port list, artifact paths, area, maturity rung (what an integrator takes, as data).
- [`porting-plan.md`](porting-plan.md) — what carries over from the same-PDK siblings.
- [`decision-records/`](decision-records/) — the decision records the spec's `[DR-n]` tags cite.
