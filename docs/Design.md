# Chess Trainer — Design

A Django web app that mines my own chess.com games for the mistakes I actually
make, turns them into puzzles, and drills me on them with spaced repetition.
The training data is my history: every puzzle is a position I have really been
in, where my next move was a blunder, a mistake, or a missed tactic —
especially the ones I repeat.

This document records the design decisions and the reasoning behind them. It
was written before the build, and the build is expected to follow it.

---

## 1. Product shape

Two puzzle types:

- **AVOID** — the position immediately before one of my errors. Task: find
  what I should have played.
- **PUNISH** — the position immediately after an opponent's error that I
  failed to exploit. Task: find the refutation I missed.

Around the puzzles: a dashboard of my weakness profile (which tactical motifs
I miss, whether that's improving), an opening-leak table (exact positions I
keep reaching and keep misplaying), and a spaced-repetition scheduler so
failed puzzles return until they stop failing.

The differentiator over Lichess's per-game "learn from your mistakes" is
**aggregation across my entire history**: recurrence counts, motif-level
stats, and the games-vs-training gap (do drilled motifs stop appearing in
real games?).

## 2. Where AI does and doesn't belong

The core pipeline is deterministic: chess.com API → Stockfish annotation →
rule-based puzzle extraction → rule-based motif detection. The app is fully
functional with zero LLM calls.

An LLM is used at exactly two edges, both at ingestion time, never in the
request path:

1. **Tier-2 motif tagging** — motifs that are miserable to rule-detect
   (deflection/overloading, zwischenzug, king-safety errors).
2. **Explanations** — a one-sentence human note per puzzle ("your knight was
   the only defender of f2 and you traded it two moves earlier").

LLM output is treated as a proposal, not a fact: responses are
schema-validated, and any proposed tag that has a deterministic checker is
verified against the board — contradictions are dropped, not stored. Tag rows
carry provenance (`rule` vs `llm`) and confidence, so the dashboard can report
what fraction of tags are rule-verified.

Rationale: LLM-in-the-request-path creates a hard runtime dependency, latency,
and unbounded cost for a feature (classification + one sentence) that is
bounded, cacheable, and runs once per puzzle. Graceful degradation is free
this way: switch tagging off and nothing else changes.

## 3. Evaluation unit: win probability, not centipawns

All thresholds are expressed in win-percentage points, converted from engine
centipawns via the standard sigmoid (as used by Lichess).

Rationale: raw centipawn thresholds misbehave at the extremes. A swing from
−8.0 to −12.0 is 400 cp of nothing (lost either way); +1.5 → 0.0 is only
150 cp but throws away most of a winning game. Win% compresses hopeless
positions and stretches the range that matters, so one threshold behaves
sensibly everywhere.

Classification: **blunder = drop ≥ 20 wp, mistake = 10–20 wp.**

**Perspective convention (invariant):** every stored win% is from the *user's*
perspective, always. Engine scores arrive relative to the side to move
(python-chess `PovScore`); the conversion to user-perspective happens exactly
once, at the engine boundary, alongside cp→wp — flip the sign whenever the
side to move is the opponent. Mate scores are not centipawns and don't go
through the sigmoid: clamp to 100 (user mates) or 0 (user is mated). Getting
this wrong corrupts every wp_drop silently — nothing crashes.

## 4. Puzzle-quality gates

**What is a candidate moment?** Two producers:

- **AVOID candidate** — a user move whose played wp drop ≥ `MISTAKE_WP_DROP`.
- **PUNISH candidate** — an opponent move that dropped the *opponent's* win%
  by ≥ `BLUNDER_WP_DROP` (equivalently: raised the user's by that much). The
  candidate position is the one after that move; `wp_before` is the user's
  win% assuming the best reply. It becomes a puzzle moment only if the user's
  *played* reply realized **less than** `PUNISH_CAPTURE_FRACTION` of the win%
  the opponent handed over — if they captured at least that fraction, they
  punished adequately and there is nothing to train.

**Every candidate moment is persisted** as a `Candidate` row (game, ply,
normalized position key, played move, wp before/after, clock, gate evidence,
verdict + rejection reason) whether or not it becomes a puzzle. That makes
recalibration a query over Candidates — in *both* directions, tightening and
loosening — without re-running the engine, and it is what backs
rejected-moments-in-stats and opening-leak promotion below.

A candidate must pass five gates:

1. **It mattered.** Win% before the move ≥ 25. Kills death-spiral blunders in
   already-lost positions. (Rejected moments still count in stats; they are
   just not puzzles.)
2. **The solution is findable.** The best move must already be the engine's
   top choice at shallow depth (~10) — a proxy for "a strong human's first
   instinct survives" — and the point must cash out within 4 mate moves or
   ~6 plies of realized gain. Engine-only quiet moves and 12-ply-deep wins
   are not puzzles.
3. **The solution is reasonably unique.** Best vs best-non-solution gap
   ≥ 10 wp. Moves within 5 wp of best join the accepted-solution set; more
   than 2 acceptable moves → discard. This gate doubles as the
   answer-checking rule, so moves within `SOLUTION_BAND_WP` of best are
   never marked wrong. (A merely-winning-but-inferior move outside the band
   *is* marked wrong — that's the point of the gap gate.)
4. **It wasn't trivial or forced.** ≤ 2 legal moves, forced recaptures, and
   book territory (ply < 10) are excluded — unless the position recurs in
   ≥ 3 **distinct games** (counted over Candidate rows — this is why gate-4
   rejections must be persisted; the first two occurrences happen before
   anyone knows it recurs), which promotes it to an **opening-leak puzzle**.
   Recurrence overrides the book exclusion.
5. **Dedup + context.** Identity is the normalized position alone (see §6);
   the same mistake across games is one puzzle with N occurrences. Every puzzle
   is tagged with phase, time control, clock bucket at the moment of the move
   (comfortable > 60 s / low 20–60 s / scramble < 20 s), and opponent-rating
   delta. Bullet games are tagged, not excluded — "only in scrambles" is a
   finding.

Gates cull; a quality score (swing × uniqueness × findability × occurrences)
ranks survivors so the best puzzles serve first. Swing is the **max** wp drop
across occurrences; the score is recomputed whenever a new occurrence is
added, so recurrence keeps promoting a puzzle. Recurrence anywhere in this
design means **distinct games**, not occurrence rows — repetitions within one
game don't inflate it.

Expected yield: ~1–3 puzzles per game. Order-of-magnitude deviations mean the
constants are wrong, not the games.

**Calibration is a first-class build step:** run the pipeline over full
history, dump 50 random surviving puzzles to a static page, and eyeball them.
Unfair (engine-only) → raise the findability bar; pointless (dead lost) →
raise gate 1. Post-launch, a per-puzzle "report" button keeps this signal
flowing.

## 5. Motif taxonomy

Three orthogonal dimensions — never flattened into one tag list:

- **Direction** (exactly one): MISSED / ALLOWED / MISCOUNTED.
- **Mechanism** (one or more): the 13 tags below.
- **Context**: phase, clock bucket, opening — from gate 5, kept separate.

Mechanism tags, by detection tier:

**Tier 1 — rule-detectable (python-chess, SEE, ray logic):** hanging piece,
fork/double attack, pin, skewer, discovered attack, back-rank, trapped piece,
counting error, mate threat, promotion/passed pawn.

**Tier 2 — LLM-proposed:** deflection/overloading/removal of the defender,
zwischenzug, king-safety error.

Plus `OTHER`, reviewed periodically as the evidence-driven expansion
mechanism. No sub-motifs (smothered mate, Greek gift, …) until the data
demands them: with one player's games most sub-motifs would have n < 5, and
"what do I do often" needs buckets big enough to mean something.

## 6. Data model

Key structural decisions (see `models.py`):

- **Puzzle vs Occurrence.** A Puzzle is identified by `position_key` alone —
  the normalized position (FEN minus move counters, en passant square kept
  only when a legal ep capture exists). The solution set is *not* part of the
  identity: it is a deterministic function of the position given an engine
  regime, and keying on it would let engine noise mint near-duplicate
  puzzles. Engine facts live on Puzzle; per-game facts (played move, clock,
  game) live on Occurrence. Recurrence count = distinct games over
  occurrences.
- **Collision policy.** Solutions are frozen at first analysis; when a later
  game reaches an existing puzzle's position, occurrences accumulate and
  engine facts are overwritten only if the new analysis is deeper (higher
  movetime). If the same position arises as AVOID in one game and PUNISH in
  another, **PUNISH wins** the `puzzle_type` (rarer, more specific prompt);
  the collision is logged.
- **Candidate is the gate ledger.** One row per gate-evaluated moment,
  puzzle or not, holding the gate evidence and verdict. Recalibration in
  either direction is a query over Candidates; rejected moments feed stats;
  opening-leak promotion counts over it.
- **Gate evidence persisted** (`uniqueness_gap_wp`, `shallow_depth_stable`
  plus the probe depth used, `cashout_plies`) for query-time re-filtering.
- **Reproducibility fields on both Game and Puzzle** (`engine_version`,
  `engine_movetime_ms`; `pipeline_version` on Game): re-runs under different
  regimes are expected and must be distinguishable — and since the engine
  facts a regime produced live on Puzzle, provenance must live there too,
  copied at creation.
- **Tag provenance on the through model** (`PuzzleMotif.source/confidence/
  rule_verified`): the propose-verify trail is data, not just pipeline
  behavior.
- **SM-2 state lives on Puzzle** (single-user). If multi-user ever happens,
  those five fields extract into `ReviewState(user, puzzle)`; nothing else
  changes.
- **WeaknessSnapshot is a rebuildable cache** for trend charts, tracking two
  distinct questions per motif: still making the mistake in games
  (occurrences), and solving it when drilled (attempts). The gap between them
  is the transfer question and the most interesting chart in the app.
- Not stored: per-move evals for *non-candidate* moments (the quiet 90% of
  plies — the PGN regenerates anything), a live MotifStats table (it's a
  query), a User FK. Candidate moments, including rejected ones, ARE stored —
  see above.

## 7. Pipeline

**Celery was considered and rejected.** It earns its keep with concurrency,
fan-out, or low-latency user-triggered background work; this system has none.
A broker + worker + beat is three daemons to babysit for minutes of batch
work per day, on a box that also runs another service.

Instead: **Django management commands, cron, and the database as the queue.**
The core principle: no stage hands anything to the next. Each command queries
for its own work by DB state, processes idempotently, and exits. A crash
loses nothing; the next run resumes from reality, which lives in Postgres.

Stages:

1. **ingest** — upsert Games from the chess.com archives API
   (`update_or_create` on the game UUID → idempotent). New games are
   `PENDING`.
2. **analyze** — for each PENDING game, in one transaction per game: engine
   pass (below) → Candidate rows → gates → `get_or_create` Puzzles / create
   Occurrences (`unique(game, ply)` makes reprocessing safe) → Tier-1
   detectors → mark ANALYZED with version fields. Per-game transactions are
   the resumability mechanism. Failures → FAILED with logged error;
   `--retry-failed` re-queues; three strikes stays failed for inspection.

   **The engine pass is two-phase.** Phase 1: a single-PV sweep over every
   ply at `--movetime` produces the wp curve and flags candidate moments
   (~1–3 per game). Phase 2, per candidate only: a MultiPV=3 probe at full
   movetime (gate 3 needs best, band-mates, and best-non-solution) plus a
   depth-`SHALLOW_DEPTH` probe (gate 2 findability). MultiPV≈3× and the
   shallow probe are paid only at candidates, so per-game cost ≈
   80 plies × movetime × (1 + ~10% candidate overhead). At 100 ms and 3,000
   games that's roughly 7–8 engine-hours — one to two niced nights on the
   Lightsail box.

   **Re-analysis is a first-class path**, not an accident: `analyze
   --reanalyze [--before-pipeline-version=X]` resets matching games to
   PENDING and reprocesses them under the collision policy in §6 (deeper
   overwrites, occurrences accumulate, Candidates replaced per game). Needed
   whenever constants can't be re-filtered by query (e.g. `SHALLOW_DEPTH`
   itself moves) or the engine regime changes.
3. **tag** — for Puzzles with `tagged_at IS NULL`, batch 10–15 per LLM call;
   schema-validate; verify checkable tags against the board; drop
   contradictions; set `tagged_at` only on success (tags + explanation are
   one joint enrichment under one timestamp), so failed batches self-requeue
   with zero retry bookkeeping. Same three-strikes rule as analyze: a
   `tag_attempts` counter per puzzle, skip after 3 and surface the skips in
   PipelineRun — otherwise one schema-breaking puzzle re-queues its batch
   forever, spending LLM money every four hours in silence. Optional by
   construction.
4. **snapshot** — nightly: delete-and-recompute the trailing-window rollups.

Wiring:

```
0 */4 * * *  flock -n /tmp/chess-pipeline.lock  nice -n 19 ionice -c 3 manage.py run_pipeline && curl -fsS $HC_PIPELINE
15 3 * * *   flock -n /tmp/chess-snapshot.lock  manage.py snapshot && curl -fsS $HC_SNAPSHOT
```

`flock` prevents overlapping runs (a long backfill makes the next pipeline
tick skip — correct, since DB-as-queue means the running instance gets to
everything). The two jobs take **separate locks** — sharing one would let a
multi-night backfill silently starve `snapshot` for days — and each has its
own healthchecks ping. Stockfish runs under `nice`/`ionice` (in the crontab
line, not just in prose) so bursts never degrade the co-hosted RAG service.

**Failure visibility:** a `PipelineRun` row per stage per run (status, counts,
error text) surfaces in the app as the pipeline-health page; the per-job
dead-man's-switch pings (healthchecks.io) on successful completion mean
silence pages me instead of hiding.

**Run zero is not a special phase** — it's the same loop pointed at a backlog:
`ingest --since=<start>` then `analyze` (manually, niced, overnight). One
knob: `--movetime`, recorded per game, so backfill may run shallower than
steady state. Hypothesis-level stats are windowed to recent games so old
games at a different skill level don't dominate; long-run trend charts use
full history.

**LLM cost:** the tag stage runs on the same box and can authenticate Claude
Code headless (`claude -p`) via a subscription OAuth token from
`claude setup-token` — or the API, since backfill is pennies and steady state
is a few puzzles a day.

## 8. Serving layer

**A solve is the line, not one move.** First move checks against the solution
set; subsequent moves check against **that solution's** stored principal
variation — each accepted solution carries its own PV, since a user opening
with solution #2 still deserves a line to play out and opponent replies to
face. The server auto-plays opponent replies from the matched PV, capped by
`cashout_plies` (≤ 3 user moves). All comparison is in UCI; SAN is display
only. V1 accepts only the PV after move one; near-misses are logged
(per-move, on the Attempt), and a tolerance band (off-PV moves within the
solution band) ships later if the logs show rage-cases.

**Serving is stateless.** The client resubmits the full move list on every
POST; the server replays it from the puzzle FEN and validates from scratch.
No session state to hold or corrupt — consistent with the server being the
sole authority on correctness.

**Grading is derived, not self-reported.** Fail → SM-2 lapse (repetitions
reset, interval ≈ 1 day, ease −0.2, floor 1.3). Success maps to an SM-2 grade
by latency and hints (clean < 30 s → 5; slow or hinted → 3–4).
`sm2_update(state, correct, latency_ms, hints_used)` is a pure function in one
module with unit tests — the one piece of logic whose bugs silently corrupt
months of scheduling.

**Hints: two-stage** (highlight the moving piece; then reveal the motif),
priced into the grade. **No free retries:** fail → full line replay + the
explanation + motif tags + link to the real game, attempt recorded, puzzle
returns via SM-2. The fail screen is the product.

**Frontend: server-rendered Django + one widget. No SPA.** chessground
(Lichess's board) + chess.js for instant client-side legality + ~150 lines of
vanilla JS; **the server is the sole authority on correctness** via
python-chess. Dashboards are templates + Chart.js over small JSON endpoints.

API surface:

```
GET  /train/next     → puzzle, orientation, context (date, opponent, clock,
                       occurrence count), prompt
POST /train/attempt  → moves, latency, hints → verdict, line, explanation,
                       next reply / completion, next_due
```

Serving order: overdue by `(due_at, -quality_score)`; when clear, introduce
new puzzles by quality with a daily cap (~10) so the run-zero corpus doesn't
firehose week one; soft-mix PUNISH and AVOID. The context block ("your game,
14 Mar, 0:22 on the clock, reached 4 times") renders prominently — it is the
emotional differentiator over generic puzzle sites.

Pages: `/train`, `/dashboard` (due count, streak, trends, motif table with
the games-vs-training gap), `/openings` (leak table), `/puzzles` (filterable
archive), `/games` (ingest/analysis status + PipelineRun history). Django
admin for CRUD. Auth: single superuser behind login middleware — it's on the
public internet, it needs a lock, not a user system.

Operational endpoints: `report` (unfair-puzzle flag → ongoing calibration)
and `bury` (skip 30 days without touching stats).

## 9. Build order

1. Models + migrations + admin
2. `ingest`
3. `analyze`: gates + Tier-1 detectors
4. **Calibration session** — 50 random puzzles on a static page; tune
   constants. Checkpoint: nothing downstream starts until the puzzles feel
   fair.
5. Train widget + SM-2
6. Dashboards + `snapshot`
7. LLM tagging (last — the app is complete without it)

## 10. Constants

All tunables live in one module (`BLUNDER_WP_DROP = 20`, `MISTAKE_WP_DROP =
10`, `SALVAGEABLE_WP_MIN = 25`, `UNIQUENESS_GAP_WP = 10`, `SOLUTION_BAND_WP =
5`, `MAX_SOLUTIONS = 2`, `SHALLOW_DEPTH = 10`, `MULTIPV = 3`,
`CASHOUT_MAX_PLIES = 6`, `MATE_MAX_MOVES = 4`, `TRIVIAL_MAX_LEGAL_MOVES = 2`,
`BOOK_PLY_CUTOFF = 10`, `OPENING_LEAK_MIN_GAMES = 3`,
`PUNISH_CAPTURE_FRACTION = 0.5`, `CLOCK_COMFORTABLE_MIN_S = 60`,
`CLOCK_SCRAMBLE_MAX_S = 20`, `NEW_PUZZLES_PER_DAY = 10`, `TAG_MAX_ATTEMPTS =
3`, `PHASE_OPENING_MAX_PLY = 20`, `PHASE_ENDGAME_MAX_PIECES = 6`,
`ENGINE_MOVETIME_MS_DEFAULT = 100`, `SM2_CLEAN_LATENCY_MS = 30000`,
`SM2_LAPSE_EASE_PENALTY = 0.2`, `SM2_MIN_EASE = 1.3`). They are defensible
defaults, expected to move during calibration, and nowhere else in the code.

Calibration log:
- **2026-07-17 (checkpoint, one-month sample):** 161 July-2026 games →
  605 candidates → 118 puzzles (0.73/game, low edge of the expected 1–3 —
  blitz-heavy month, gate 3 culling hardest: 362 of 487 rejections).
  Mix: 61 AVOID / 57 PUNISH across all phases; motifs led by hanging-piece
  (40), fork (23), pin (16); 39 puzzles rule-untagged (Tier-2 headroom);
  no opening leaks yet (expected — needs the full backfill for 3-game
  recurrence). Eyeballed and accepted as-is; constants unchanged.
  Revisit the knobs before the full-history backfill.

Build-time constant notes (§10 log):
- Phase classification and SM-2 grading thresholds joined the module during
  the build (steps 3 and 5 prep) — same calibration rules apply.
- Stack note: Python 3.13 (no 3.12 on the dev machine; Django 5.2 LTS
  supports 3.13).

## 11. Stack

Django + Postgres (SQLite in dev), python-chess, Stockfish (local),
chess.com public API, chessground + chess.js, Chart.js, cron + flock on an
existing Lightsail instance, Claude (headless or API) for the optional
tagging stage.
