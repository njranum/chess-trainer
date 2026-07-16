# CLAUDE.md — Chess Trainer

Django app that mines my own chess.com games into personal puzzles (positions
where I blundered, erred, or missed a tactic), tags them by motif, and drills
me with spaced repetition.

**`docs/Design.md` is the source of truth.** Every architectural decision in
this repo was settled there before coding started, with rationale. If a task
seems to require deviating from it, stop and say so explicitly — don't
silently diverge. If Design.md and code disagree, flag it; don't pick one
quietly.

## Current state

Design complete; build follows docs/Design.md §9 order:

1. [x] Models + migrations + admin  (the designed schema from the old root
       `models.py` now lives split across the apps listed under Conventions
       below, comments intact)
2. [x] `ingest` command
3. [ ] `analyze` command (gates + Tier-1 motif detectors)
4. [ ] **Calibration checkpoint** — 50 random puzzles on a static page,
       tune constants. Do NOT build past this until puzzles feel fair.
5. [ ] Train widget + SM-2
6. [ ] Dashboards + `snapshot`
7. [ ] LLM tagging (optional by construction — app must be complete without it)

Update these checkboxes as steps land.

## Hard invariants (violating these = wrong, even if tests pass)

- **The database is the queue.** Pipeline stages never pass data to each
  other; each management command queries for its own work by DB state, is
  idempotent, and exits. Re-running any stage must always be safe.
- **Per-game transactions in `analyze`.** A crash mid-run leaves N fully
  analyzed games and the rest PENDING. Never a half-analyzed game.
- **Server is the sole authority on move correctness** (python-chess).
  Client-side chess.js legality is UX only.
- **No LLM in the request path.** LLM calls happen only in the `tag`
  management command, at ingestion time, batched. LLM output is a proposal:
  schema-validate, verify checkable tags against the board, drop
  contradictions, set `tagged_at` only on success.
- **All tunable thresholds live in one constants module** and nowhere else.
  No literal 20.0s scattered in gate code.
- **Evals are win-percentage points**, converted from centipawns via the
  standard sigmoid, everywhere past the raw engine boundary. Never compare
  raw centipawns against thresholds.
- **All stored win% are from the user's perspective.** Engine scores are
  side-to-move — flip the sign at the boundary when the opponent moves, or
  every wp_drop is silently garbage. Mate scores clamp to 100/0; the sigmoid
  never sees them.
- **`sm2_update()` stays a pure function** in its own module with exhaustive
  unit tests. It takes state + attempt facts, returns new state, touches
  nothing.
- **Puzzle identity is `position_key` alone** (FEN minus move counters, ep
  normalized). Solutions freeze at first analysis; deeper re-analysis may
  overwrite engine facts. Recurrence = distinct games over Occurrence rows,
  never duplicate Puzzles.
- **Every gate-evaluated moment writes a `Candidate` row**, accepted or
  rejected — recalibration is a query over Candidates, and opening-leak
  promotion depends on rejected rows existing.
- **No new daemons.** No Celery, no Redis, no workers. cron + flock +
  management commands. (Rejected deliberately — see docs/Design.md §7.)
- **No SPA.** Server-rendered Django templates + chessground + vanilla JS.

## Stack

Django 5.x / Python 3.12 · Postgres (prod, Lightsail) / SQLite (dev) ·
python-chess · Stockfish (local binary; path via env `STOCKFISH_PATH`) ·
chessground + chess.js (vendored static, no npm build step) · Chart.js ·
pytest + pytest-django.

## Commands

```bash
# dev
python manage.py runserver
pytest                                  # run before claiming anything works
ruff check . && ruff format .

# pipeline (each idempotent, each re-runnable)
python manage.py ingest [--since=YYYY-MM]
python manage.py analyze [--retry-failed] [--movetime=MS] [--reanalyze [--before-pipeline-version=X]]
python manage.py tag
python manage.py snapshot
python manage.py run_pipeline           # ingest → analyze → tag
python manage.py calibrate --sample=50  # step 4: static HTML dump for eyeballing
```

(Commands that don't exist yet: create them matching these names/flags.)

## Conventions

- Apps: `games` (Game, ingest), `puzzles` (Puzzle/Occurrence/motifs, analyze,
  tag), `training` (Attempt, SM-2, serving views), `dashboard` (snapshot,
  charts). Keep pipeline code in `management/commands/` + a `pipeline/`
  module per app for testable logic — commands stay thin wrappers.
- Every pipeline stage writes a `PipelineRun` row (stage, status, counts,
  error text). Add the model early; it's also the /games health page.
- Chess correctness tests use fixed FENs with known engine-verified answers,
  committed as fixtures — never call Stockfish in unit tests. Mark the few
  integration tests that need the real engine with `@pytest.mark.engine`.
- Gate logic tests are table-driven: (position facts, expected gate verdict)
  rows. When calibration changes a constant, tests should mostly not change.
- UK English in user-facing copy.

## Gotchas already known

- chess.com archive months are immutable except the current month —
  re-ingest the current month every run, cache earlier ones.
- Clock data (`%clk`) lives in PGN comments; some older/daily games lack it.
  `clock_seconds` is nullable — handle absence, don't fabricate.
- `position_key` must strip halfmove/fullmove counters BEFORE hashing or
  dedup silently fails (identical positions look distinct). Same trap one
  field over: normalize en passant — keep the ep square only when a legal ep
  capture exists (`board.epd(en_passant="legal")`-style), or a vestigial ep
  square after any double push splits identical positions.
- SEE (static exchange evaluation) in python-chess is not built in as a
  one-liner — the counting-error and hanging-piece detectors need a careful
  implementation; test it against known exchange sequences.
- Stockfish on the Lightsail box must run under `nice`/`ionice` (shares the
  box with the RAG service). Use `--movetime`, not fixed depth, for
  predictable runtime.
- Multi-move puzzle serving: first move checks the solution set; later moves
  check the PV only (v1). Log near-misses instead of accepting them.

## When working in this repo

- Read the `docs/Design.md` section for the area you're touching before
  writing code.
- Small commits per build step; don't mix pipeline and serving changes.
- If a gate/threshold behaves badly on real data, change the constant, note
  it in docs/Design.md §10, and say what you observed — never special-case
  around a constant.
- Never commit secrets: `CLAUDE_CODE_OAUTH_TOKEN`, DB creds, and
  `STOCKFISH_PATH` come from the environment (`.env` is gitignored).
- Don't invent chess facts. If a detector or test needs a position with a
  known property, construct it with python-chess and verify programmatically.
