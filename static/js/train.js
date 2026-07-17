// Train widget (Design.md §8): chessground board + chess.js for instant
// client-side legality (UX only — the server re-validates every line).
// Stateless protocol: every POST resends the full user move list.

import { Chessground } from "/static/vendor/chessground.min.js";
import { Chess } from "/static/vendor/chess.js";

const $ = (id) => document.getElementById(id);
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];

let state = null; // {puzzle, chess, moves, hintsUsed, startedAt, solved}
let board = null;

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function dests(chess) {
  // chess.js verbose moves → chessground's {from: [to, ...]} map.
  const map = new Map();
  for (const m of chess.moves({ verbose: true })) {
    if (!map.has(m.from)) map.set(m.from, []);
    map.get(m.from).push(m.to);
  }
  return map;
}

function setBoard(fen, orientation, movable) {
  const chess = new Chess(fen);
  const config = {
    fen,
    orientation,
    turnColor: chess.turn() === "w" ? "white" : "black",
    movable: movable
      ? { free: false, color: orientation, dests: dests(chess),
          events: { after: onUserMove } }
      : { free: false, color: undefined, dests: new Map() },
    animation: { duration: 200 },
  };
  if (board) board.set(config);
  else board = Chessground($("board"), config);
  return chess;
}

async function loadNext() {
  const data = await api("/train/next");
  $("feedback").className = "feedback";
  if (data.done) {
    $("train").hidden = true;
    $("done").hidden = false;
    return;
  }
  $("train").hidden = false;
  $("done").hidden = true;
  state = { puzzle: data, moves: [], hintsUsed: 0,
            startedAt: Date.now(), finished: false };
  state.chess = setBoard(data.fen, data.orientation, true);
  $("prompt").textContent = data.prompt;
  const c = data.context;
  $("context").textContent = c.date
    ? `Your game, ${c.date}, vs ${c.opponent} (${c.opponent_rating}) · ${c.time_class}`
      + (c.clock_seconds ? ` · ${Math.round(c.clock_seconds)}s on the clock` : "")
      + (c.occurrence_count > 1 ? ` · reached ${c.occurrence_count} times` : "")
    : "";
  $("due-count").textContent = `${data.due_count} due`;
}

function uciOf(orig, dest) {
  // Promotion: auto-queen (v1 simplification, logged server-side as-is).
  const piece = state.chess.get(orig);
  const promo = piece?.type === "p" && (dest[1] === "8" || dest[1] === "1") ? "q" : "";
  return orig + dest + promo;
}

async function onUserMove(orig, dest) {
  if (state.finished) return;
  const uci = uciOf(orig, dest);
  state.chess.move({ from: orig, to: dest, promotion: "q" });
  state.moves.push(uci);
  const result = await api("/train/attempt", {
    puzzle_id: state.puzzle.puzzle_id,
    moves: state.moves,
    hints_used: state.hintsUsed,
    latency_ms: Date.now() - state.startedAt,
  });
  if (result.status === "continue") {
    playReply(result.opponent_reply);
  } else {
    state.finished = true;
    showOutcome(result);
  }
}

function playReply(uci) {
  state.chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4),
                     promotion: uci[4] || undefined });
  board.move(uci.slice(0, 2), uci.slice(2, 4));
  board.set({ fen: state.chess.fen(), turnColor: state.puzzle.orientation,
              movable: { free: false, color: state.puzzle.orientation,
                         dests: dests(state.chess),
                         events: { after: onUserMove } } });
}

function showOutcome(result) {
  const solved = result.status === "solved";
  $("feedback").className = `feedback ${solved ? "success" : "failure"}`;
  $("feedback-title").innerHTML = solved
    ? `<strong>Solved</strong> — grade ${result.grade}, next due ${result.next_due.slice(0, 10)}`
    : "<strong>Not this time.</strong> The line was:";
  $("feedback-line").textContent = result.solution_line_san.join(" ");
  $("feedback-motifs").innerHTML = result.motifs
    .map((m) => `<span class="motif-tag">${m}</span>`).join("");
  $("feedback-explanation").textContent = result.explanation || "";
  $("feedback-game").innerHTML = !solved && result.game_url
    ? `In the game you played <strong>${result.played_in_game}</strong> — ` +
      `<a href="${result.game_url}" target="_blank" rel="noopener">view the game</a>`
    : "";
  if (!solved) replayLine(result.solution_line_uci);
}

function replayLine(pv) {
  // The fail screen is the product: play the whole solution out slowly.
  const replay = new Chess(state.puzzle.fen);
  board.set({ fen: state.puzzle.fen, movable: { free: false, dests: new Map() } });
  pv.forEach((uci, i) => {
    setTimeout(() => {
      replay.move({ from: uci.slice(0, 2), to: uci.slice(2, 4),
                    promotion: uci[4] || undefined });
      board.move(uci.slice(0, 2), uci.slice(2, 4));
      board.set({ fen: replay.fen() });
    }, 700 * (i + 1));
  });
}

$("hint").addEventListener("click", () => {
  if (!state || state.finished) return;
  state.hintsUsed = Math.min(state.hintsUsed + 1, 2);
  if (state.hintsUsed === 1) {
    board.setShapes([{ orig: state.puzzle.hints.from_square, brush: "green" }]);
  } else {
    const motifs = state.puzzle.hints.motifs;
    $("context").textContent =
      "Motifs: " + (motifs.length ? motifs.join(", ") : "no rule tags — trust the position");
  }
});

$("bury").addEventListener("click", async () => {
  await api("/train/bury", { puzzle_id: state.puzzle.puzzle_id });
  loadNext();
});

$("report").addEventListener("click", async () => {
  const note = prompt("What's wrong with this puzzle? (optional)") || "";
  await api("/train/report", { puzzle_id: state.puzzle.puzzle_id, note });
  loadNext();
});

$("next").addEventListener("click", loadNext);

loadNext();
