"""
Calibration page builder (Design.md §4, build step 4): a static, standalone
HTML dump of sampled puzzles with everything needed to judge each one fair
or unfair at a glance — board, prompt, context, solution line, and the gate
evidence that let it through.
"""

import html

import chess
import chess.svg

PROMPTS = {
    "avoid": "Find the move you should have played.",
    "punish": "Your opponent just went wrong — find the refutation you missed.",
}

PAGE_TEMPLATE = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<title>Calibration sample — {count} puzzles</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
         color: #222; }}
  .puzzle {{ border: 1px solid #ccc; border-radius: 8px; padding: 1.2rem;
             margin-bottom: 2rem; display: flex; gap: 1.5rem; flex-wrap: wrap; }}
  .board {{ flex: 0 0 360px; }}
  .facts {{ flex: 1; min-width: 20rem; }}
  .prompt {{ font-weight: 600; font-size: 1.05rem; }}
  .context, .evidence {{ color: #555; font-size: 0.9rem; margin-top: .6rem; }}
  details {{ margin-top: .8rem; }}
  summary {{ cursor: pointer; color: #0645ad; }}
  .verdictbox {{ margin-top: .8rem; font-size: .9rem; color: #777; }}
  h1 {{ font-size: 1.3rem; }}
</style>
</head>
<body>
<h1>Calibration sample — {count} puzzles</h1>
<p>Judge each one: <em>fair</em> (you'd accept it from a coach), <em>unfair</em>
(engine-only), or <em>pointless</em> (already lost / trivial). Tune the §10
constants accordingly and record observations in Design.md §10.</p>
{puzzles}
</body>
</html>
"""

PUZZLE_TEMPLATE = """
<div class="puzzle" id="puzzle-{id}">
  <div class="board">{svg}</div>
  <div class="facts">
    <div class="prompt">#{id} · {type_label} · {phase} · {prompt}</div>
    <div class="context">{context}</div>
    <details>
      <summary>Solution &amp; evidence</summary>
      <p><strong>Solutions:</strong> {solutions}</p>
      <p><strong>You played:</strong> {played}</p>
      <div class="evidence">
        wp before {wp_before:.1f} · max drop {max_drop:.1f} ·
        uniqueness gap {gap:.1f} wp · cashout {cashout} plies ·
        shallow-stable {stable} · quality {quality:.4f} ·
        motifs: {motifs}{leak}
      </div>
    </details>
    <div class="verdictbox">fair / unfair / pointless — note it down</div>
  </div>
</div>
"""


def build_calibration_html(puzzles) -> str:
    blocks = [_puzzle_block(p) for p in puzzles]
    return PAGE_TEMPLATE.format(count=len(blocks), puzzles="\n".join(blocks))


def _puzzle_block(puzzle) -> str:
    board = chess.Board(puzzle.fen)
    svg = chess.svg.board(board, orientation=board.turn, size=360)

    occurrences = list(puzzle.occurrences.select_related("game"))
    context_bits = []
    for occ in occurrences[:4]:
        game = occ.game
        clock = f", {occ.clock_seconds:.0f}s on the clock" if occ.clock_seconds else ""
        context_bits.append(
            f"{game.end_time:%d %b %Y} vs {html.escape(game.opponent_username)}"
            f" ({game.time_class}{clock})"
        )
    reached = f"Reached in {len(occurrences)} game(s): " if occurrences else ""

    solutions = "; ".join(
        f"{html.escape(s['san'])} ({s['win_pct']:.1f} wp)"
        + (f" — line: {html.escape(_pv_line(puzzle.fen, s['pv_uci']))}"
           if s.get("pv_uci") else "")
        for s in puzzle.solutions
    )
    played = ", ".join(
        f"{html.escape(o.played_san)} (→ {o.win_pct_after_played:.1f} wp)"
        for o in occurrences[:4]
    ) or "—"
    max_drop = max(
        (puzzle.win_pct_before - o.win_pct_after_played for o in occurrences),
        default=0.0,
    )
    motifs = ", ".join(puzzle.motifs.values_list("slug", flat=True)) or "none (rule tier)"

    return PUZZLE_TEMPLATE.format(
        id=puzzle.pk,
        svg=svg,
        type_label=puzzle.get_puzzle_type_display().upper(),
        phase=puzzle.phase,
        prompt=PROMPTS[puzzle.puzzle_type],
        context=reached + "; ".join(context_bits),
        solutions=solutions,
        played=played,
        wp_before=puzzle.win_pct_before,
        max_drop=max_drop,
        gap=puzzle.uniqueness_gap_wp,
        cashout=puzzle.cashout_plies,
        stable="yes" if puzzle.shallow_depth_stable else "no",
        quality=puzzle.quality_score,
        motifs=motifs,
        leak=" · OPENING LEAK" if puzzle.is_opening_leak else "",
    )


def _pv_line(fen: str, pv_uci: list[str]) -> str:
    board = chess.Board(fen)
    sans = []
    for uci in pv_uci:
        move = chess.Move.from_uci(uci)
        sans.append(board.san(move))
        board.push(move)
    return " ".join(sans)
