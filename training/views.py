"""Training views (Design.md §8). The server is the sole authority on move
correctness; these endpoints replay every submitted line via python-chess."""

import json
from datetime import timedelta

import chess
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from puzzles.constants import BURY_DAYS
from puzzles.models import Puzzle
from training.lines import IllegalLine, evaluate_line
from training.models import Attempt, Report
from training.serving import due_count, next_puzzle
from training.sm2 import Sm2State, sm2_update


def train_page(request):
    return render(request, "training/train.html")


@require_GET
def next_api(request):
    puzzle = next_puzzle()
    if puzzle is None:
        return JsonResponse({"done": True, "due_count": due_count()})

    board = chess.Board(puzzle.fen)
    occurrence = (puzzle.occurrences.select_related("game")
                  .order_by("-game__end_time").first())
    context = {}
    if occurrence is not None:
        game = occurrence.game
        context = {
            "date": game.end_time.strftime("%d %b %Y"),
            "opponent": game.opponent_username,
            "opponent_rating": game.opponent_rating,
            "time_class": game.time_class,
            "clock_seconds": occurrence.clock_seconds,
            "game_url": game.url,
            "occurrence_count": puzzle.occurrence_count,
        }
    prompts = {
        "avoid": "Find the move you should have played.",
        "punish": "Your opponent just went wrong — find the refutation.",
    }
    return JsonResponse({
        "done": False,
        "puzzle_id": puzzle.pk,
        "fen": puzzle.fen,
        "orientation": "white" if board.turn == chess.WHITE else "black",
        "puzzle_type": puzzle.puzzle_type,
        "prompt": prompts[puzzle.puzzle_type],
        "phase": puzzle.phase,
        "is_opening_leak": puzzle.is_opening_leak,
        "context": context,
        "due_count": due_count(),
        # Hint payload (single-user app: shipping this to the client is a
        # deliberate v1 simplification; hints are priced into the grade).
        "hints": {
            "from_square": puzzle.solutions[0]["uci"][:2],
            "motifs": list(puzzle.motifs.values_list("name", flat=True)),
        },
    })


@require_POST
def attempt_api(request):
    payload = json.loads(request.body)
    puzzle = Puzzle.objects.get(pk=payload["puzzle_id"])
    moves = payload.get("moves", [])
    try:
        verdict = evaluate_line(puzzle.fen, puzzle.solutions,
                                puzzle.cashout_plies, moves)
    except IllegalLine as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if verdict.status == "continue":
        return JsonResponse({"status": "continue",
                             "opponent_reply": verdict.opponent_reply_uci})

    # Terminal: record the attempt and reschedule (SM-2).
    hints_used = int(payload.get("hints_used", 0))
    latency_ms = payload.get("latency_ms")
    correct = verdict.status == "solved"
    result = sm2_update(
        Sm2State(interval_days=puzzle.interval_days,
                 ease_factor=puzzle.ease_factor,
                 repetitions=puzzle.repetitions,
                 lapses=puzzle.lapses),
        correct=correct, latency_ms=latency_ms, hints_used=hints_used,
    )
    Attempt.objects.create(
        puzzle=puzzle, moves=verdict.moves_log, correct=correct,
        failed_at_ply=verdict.failed_at_ply, latency_ms=latency_ms,
        hints_used=hints_used, grade=result.grade,
    )
    now = timezone.now()
    puzzle.interval_days = result.state.interval_days
    puzzle.ease_factor = result.state.ease_factor
    puzzle.repetitions = result.state.repetitions
    puzzle.lapses = result.state.lapses
    puzzle.due_at = now + timedelta(days=result.state.interval_days)
    puzzle.save(update_fields=["interval_days", "ease_factor", "repetitions",
                               "lapses", "due_at"])

    solution = _matched_or_primary(puzzle, moves)
    pv = solution.get("pv_uci") or [solution["uci"]]
    response = {
        "status": verdict.status,
        "grade": result.grade,
        "next_due": puzzle.due_at.isoformat(),
        "solution_line_uci": pv,
        "solution_line_san": _line_san(puzzle.fen, pv),
        "motifs": list(puzzle.motifs.values_list("name", flat=True)),
        "explanation": puzzle.explanation,
    }
    if verdict.status == "failed":
        occurrence = (puzzle.occurrences.select_related("game")
                      .order_by("-game__end_time").first())
        response["failed_at_ply"] = verdict.failed_at_ply
        response["game_url"] = occurrence.game.url if occurrence else ""
        response["played_in_game"] = occurrence.played_san if occurrence else ""
    return JsonResponse(response)


@require_POST
def bury_api(request):
    payload = json.loads(request.body)
    puzzle = Puzzle.objects.get(pk=payload["puzzle_id"])
    puzzle.buried_until = timezone.now() + timedelta(days=BURY_DAYS)
    puzzle.save(update_fields=["buried_until"])  # SM-2 state untouched
    return JsonResponse({"status": "buried",
                         "until": puzzle.buried_until.isoformat()})


@require_POST
def report_api(request):
    payload = json.loads(request.body)
    puzzle = Puzzle.objects.get(pk=payload["puzzle_id"])
    Report.objects.create(puzzle=puzzle, note=payload.get("note", ""))
    return JsonResponse({"status": "reported"})


def _matched_or_primary(puzzle, moves):
    if moves:
        for s in puzzle.solutions:
            if s["uci"] == moves[0]:
                return s
    return puzzle.solutions[0]


def _line_san(fen: str, pv_uci: list[str]) -> list[str]:
    board = chess.Board(fen)
    sans = []
    for uci in pv_uci:
        move = chess.Move.from_uci(uci)
        sans.append(board.san(move))
        board.push(move)
    return sans
