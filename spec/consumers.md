# Consumers — who takes this block, and what they need

This block's consumers are part of its spec (2am cross-cutting rule 9,
`2am/REUSE.md` §"Adopt or record", ratified
[2am#899](https://github.com/2AMLogic/2am/issues/899)): the repos that
declare `consumes: sg13g2-opamp` in `2am/repos.yml` are named here, with
the requirement rows each imposes and a per-row verdict against this
block's ratified spec — **meets / does not meet / unknown** ("unknown" is
a legitimate verdict; an unnamed row or an unmeasured value is not).

**Nothing on this page changes any ratified row of
[`target-spec.md`](target-spec.md).** It is additive consumer-facing
documentation; no decision record is needed because no target, bound, or
scope line moves. The structured, machine-readable companion to this file
is [`integrator.json`](integrator.json) (top cell, ports, artifact paths,
area, maturity rung — what an integrator takes, as data).

**Edge provenance (re-read live 2026-09-22, not quoted from memory):**

- `2AMLogic/2am` `repos.yml` @ **`79b7cc6`** — the operator-governed
  source of truth for `consumes` edges (per `2am/REUSE.md` §"The three
  edges", they can change independently of this repo — re-verify the live
  file before relying on this list).
- `2AMLogic/sg13g2-bandgap` @ **`463c1af`** (moved since this issue's
  curation read `090dc5e`; its `design/bandgap_amp.sch` and
  `spec/porting-plan.md` DR-0002 were re-read at the newer SHA).
- `2AMLogic/sg13g2-ldo` @ **`4fbfa18`**.
- This repo @ **`9d49d96`** (the `main` this pass branched from).

Exactly two repos declare the edge today:

```yaml
# 2am/repos.yml @ 79b7cc6
sg13g2-bandgap:
    consumes: [sg13g2-opamp]
sg13g2-ldo:
    consumes: [sg13g2-opamp, sg13g2-bandgap]   # error amp is an ideal placeholder today - the opamp canary is its real one
```

---

## sg13g2-bandgap — not the same block, and recorded as such

**Not the same block.** `sg13g2-bandgap`'s in-tree amplifier
(`design/bandgap_amp.sch`, read @ `463c1af`) is a **single-stage,
current-mirror-folded OTA built entirely on HV (3.3 V) devices** — PMOS
input pair (`sg13_hv_pmos` legs), folded through an NMOS-then-PMOS mirror
chain — servoing a fixed, narrow common-mode point near one V_BE
(~0.7–0.8 V, near vss) to close `bandgap_core.sch`'s loop. That is a
different device voltage class, a different stage count, and a fixed CM
point, versus this block's ratified scope: a **two-stage,
Miller-compensated, general-purpose** op-amp on **1.2 V LV devices**
([`0001-topology-and-cl.md`](decision-records/0001-topology-and-cl.md)
[DR-1]; `target-spec.md` §1 Scope). Per `2am/REUSE.md`'s duplication table
("Same name, different block … Not duplication. Say so in the spec once,
by name"): this is recorded here, once, as **not the same block** — the
`consumes` edge records that a relationship exists, not that this canary
is a drop-in replacement for `bandgap_amp.sch`, and `bandgap_amp.sch` is
not a duplicate of this block that needs retiring.

Requirement rows (the consumer's side read from its own tree, not assumed;
this block's side from `target-spec.md` as ratified):

| Requirement | Consumer's stated need | This block (ratified) | Verdict |
|---|---|---|---|
| Supply / device voltage class | **3.3 V ±10 %, HV flavor** primary (its DR-0002, `spec/porting-plan.md` §4/§6: `sg13_hv_*`, `V_GS ≤ 3.3 V max`) | **1.2 V ±10 % LV only** (`sg13_lv_*`); the 3.3 V HV flavor is an explicitly **unopened** stretch row (`target-spec.md` §1) | **does not meet** — wrong voltage class; would require the HV stretch to be opened by its own decision record on this side |
| Port list | `bandgap_amp`: `in_p in_n out vdd vss` — no `ibias` pin (bias folded in-tree) | `vdd vss inn inp out ibias` — requires an **external 10 µA `ibias` reference** (on-die bias out of scope per `design/opamp_sizing.md` "Bias scope") | **does not meet as-is** — integrator must supply the `ibias` reference the consumer's own amp does not need |
| Input common-mode range | Fixed ~0.7–0.8 V (one V_BE, near vss) at a 3.3 V rail | Measured ICMR worst-span 0.6158–0.8690 V, guaranteed envelope 0.6401–0.7954 V — at the **1.2 V** rail, `[P]` measured-not-ratified (`sim/input-cmr/`) | **does not meet at the consumer's rail** (block not qualified at 3.3 V); at this block's own 1.2 V rail the need sits inside the measured envelope, noted as context only |
| GBW / speed | No amplifier-level row exists in the consumer's spec — only host rows (TC < 50 ppm/°C, startup < 1 ms, PSRR > 60 dB @ DC) | GBW ≥ 4.74 MHz worst-case into 2 pF [DR-2] | **unknown** — consumer states no amplifier-level requirement to compare |
| Offset | No amplifier-level row | Systematic +21.9 mV worst [DR-2]; mismatch-driven 3σ 26.4–27.4 mV measured [P] | **unknown** — no consumer row to compare |
| Noise | No amplifier-level row (host spec has no amp-noise row) | ≤ 108.9 µVrms integrated 100 Hz–1 MHz [DR-2] | **unknown** — no consumer row to compare |
| Area budget | Host-level total < 0.05 mm² (bandgap block, not the amp alone) | `[TBD-12]` — no layout exists ([#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29)) | **unknown — not yet measurable** (no layout on this block; the consumer's figure is a host-level total, not an amp-level budget) |

## sg13g2-ldo — the canary is named as its real error amp; its spec has not caught up

`2am/repos.yml`'s inline comment is explicit: *"error amp is an ideal
placeholder today - the opamp canary is its real one."* The design-side
reality (read @ `4fbfa18`): `design/ldo_erramp_placeholder.sch` is an
**ideal ~100k-gain VCVS** — no PDK device, no gain stage, no bias network
— with pins `INP INN OUT VSS` (no `VDD`); its own header states a real
amplifier's full pin list is renegotiated when it replaces the cell.
So this consumer's rows are almost entirely **not yet stated** — the LDO
has an intent, not an amplifier-level requirement set.

| Requirement | Consumer's stated need | This block (ratified) | Verdict |
|---|---|---|---|
| Supply / device voltage class | 3.3 V-primary (same SG13G2 HV-first posture as the bandgap twin; `target-spec.md` §1's own note records both consumers as 3.3 V-primary) | 1.2 V ±10 % LV only; HV unopened | **does not meet** — same voltage-class gap as above; adopting this canary as-is needs the HV question answered on this side or a level-shift scheme on the consumer side |
| Port list | Placeholder `INP INN OUT VSS`, no `VDD` — header says pins are renegotiated on replacement | `vdd vss inn inp out ibias` | **unknown — not yet negotiated** (the placeholder's header defers the pin list to the replacement decision; this block's list is the opening position, `ibias` reference included) |
| Iq | No SG13G2 row of its own; its `spec/porting-plan.md` §2.2 cites gf180's ≈16–26 µA **total-block** allocation (10 µA stretch) as the anchor | Iq ≤ 119.7 µA worst-case total (incl. the external 10 µA `ibias` reference) [DR-2] | **does not meet** the cited allocation anchor — 119.7 µA exceeds 16–26 µA by ~5×; the consumer has not yet set its own SG13G2 number, so this is a gap to record, not a verdict on a ratified consumer row |
| Offset | §2.2 cites gf180's 36 mV 3σ regulator-only budget as the anchor | Systematic +21.9 mV worst [DR-2] + mismatch-driven 3σ 26.4–27.4 mV [P] → worst single-PVT total **46.7 mV** [P], not yet re-ratified | **does not meet** the cited anchor (46.7 mV > 36 mV; even the 3σ random term alone, 27.4 mV, plus any systematic share crowds it) |
| GBW / speed, noise | No rows (the LDO spec defers all amplifier-level rows to the error-amp decision) | GBW ≥ 4.74 MHz [DR-2]; ≤ 108.9 µVrms [DR-2] | **unknown** — no consumer rows to compare |
| Input common-mode range | Not stated (VREF is an external black-box port; feedback divider node undefined at 3.3 V) | Measured ICMR 0.6158–0.8690 V worst-span [P] | **unknown** — consumer has not stated the error-amp CM requirement |
| Area budget | No amp-level budget | `[TBD-12]` — no layout ([#29](https://github.com/2AMLogic/sg13g2-opamp/issues/29)) | **unknown — not yet measurable** |

### Discrepancy filed on the consumer (the `sky130-sar-adc#346` pattern)

The consumer's own `spec/porting-plan.md` §2.2 "Error amplifier" still
treats input-stage device choice (CMOS vs bipolar `npn13G2l`), Iq cost,
and reference interface as **open** questions and never mentions
`sg13g2-opamp` (zero occurrences, verified @ `4fbfa18`) — i.e. the
consumer's spec has not caught up to the `repos.yml` edge asserting this
canary is its real error amp. Per the pattern named in `2am/REUSE.md`,
that finding belongs **on the consumer**, not only in this repo:
filed as
[2AMLogic/sg13g2-ldo#50](https://github.com/2AMLogic/sg13g2-ldo/issues/50)
(2026-09-22, from this issue's pass).

---

## Maintenance

- The `consumes` edges are **operator-governed** (`2am/REUSE.md` §"The
  three edges") and can change independently of this repo. Re-read the
  live `2am/repos.yml` (and cite its commit, per `2am/REUSE.md`'s
  "Porting plans cite commits" convention) before updating this page —
  never restate the edges from memory.
- Per-row "unknown" verdicts here are prompts, not conclusions: when a
  consumer states an amplifier-level row (or this block gains the missing
  evidence — layout for area, ratification for the `[P]` figures), update
  the row and its verdict in the same pass.
- Findings about a consumer's own block are filed on the consumer repo
  and linked here (`sg13g2-ldo#50` above is the first), never recorded
  only in this repo.
