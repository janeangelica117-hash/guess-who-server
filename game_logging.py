"""
game_logging.py — shared logging setup, used by BOTH server.py and the
desktop client (game_engine.py), each pointed at its own folder:

  - server.py calls setup_logging() with no log_dir, so logs land in
    ./logs next to server.py on the host.
  - game_engine.py calls setup_logging(log_dir=..., console=False) so
    logs land in a writable per-user folder (~/.guesswho/logs) instead
    of wherever the packaged .exe happens to be installed, and so it
    never tries to write to a console the windowed build doesn't have.

Three loggers, same idea as the "logging module" walkthrough (loggers,
levels, handlers, formatters) but split so each kind of output stays
readable on its own:

  "guesswho"            general app log — connects, matches, admin
                         actions, errors. Console at INFO, rotating file
                         at DEBUG. Replaces the old print() calls.

  "guesswho.games"      ONE JSON object per finished/abandoned game,
                         written to <log_dir>/gameplay.log. Meant for
                         later analysis — pandas.read_json(path,
                         lines=True) turns it into a table you can
                         group by category/result.

  "guesswho.games.txt"  the SAME events, but as one plain, human-
                         readable line each, written to
                         <log_dir>/game_history.txt (and echoed to the
                         console, when console=True). This is the
                         "just open it and read it" record of what
                         players did.

Call setup_logging() once, before any handler runs. GAME_HISTORY_PATH /
GAMEPLAY_JSON_PATH point at the two output files so other code (e.g.
the server's admin download route) doesn't have to reconstruct the
path itself — they're only valid after setup_logging() has run.
"""
import json
import logging
import logging.handlers
import os
import time

_DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

LOG_DIR            = _DEFAULT_LOG_DIR
GAME_HISTORY_PATH  = os.path.join(LOG_DIR, "game_history.txt")
GAMEPLAY_JSON_PATH = os.path.join(LOG_DIR, "gameplay.log")

_configured = False


def setup_logging(console_level=logging.INFO, file_level=logging.DEBUG,
                   log_dir=None, console=True):
    """
    log_dir  — where the logs/ folder goes. Defaults to next to this
               file (right for the server). Pass an explicit writable
               folder for the desktop client, e.g.:
                   os.path.join(os.path.expanduser("~"), ".guesswho", "logs")
    console  — set False for the windowed desktop build, which has no
               console to write to.
    """
    global _configured, LOG_DIR, GAME_HISTORY_PATH, GAMEPLAY_JSON_PATH
    if _configured:
        return
    _configured = True

    LOG_DIR = log_dir or _DEFAULT_LOG_DIR
    GAME_HISTORY_PATH  = os.path.join(LOG_DIR, "game_history.txt")
    GAMEPLAY_JSON_PATH = os.path.join(LOG_DIR, "gameplay.log")

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        # Can't create the logs folder (read-only filesystem, no
        # permission, etc.) — fall through and continue. The file
        # handlers below are each wrapped in their own try/except OSError
        # too, so they'll just silently no-op instead of writing, and
        # console logging (if enabled) still works. The one thing this
        # function must NEVER do is raise, since both server.py and
        # game_engine.py call it at import time — an exception here
        # would crash the entire app before it even starts.
        pass

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── general app logger ──────────────────────────────────────────────
    app_logger = logging.getLogger("guesswho")
    app_logger.setLevel(logging.DEBUG)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        app_logger.addHandler(console_handler)

    try:
        app_file = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "app.log"), maxBytes=1_000_000, backupCount=3,
        )
        app_file.setLevel(file_level)
        app_file.setFormatter(formatter)
        app_logger.addHandler(app_file)
    except OSError:
        # Read-only or missing disk — console logging (if enabled)
        # above still works, just skip the file handler.
        pass

    # ── gameplay event logger — JSON, for analysis later ────────────────
    game_logger = logging.getLogger("guesswho.games")
    game_logger.setLevel(logging.INFO)
    game_logger.propagate = False  # keep these out of app.log / console noise

    try:
        game_file = logging.handlers.RotatingFileHandler(
            GAMEPLAY_JSON_PATH, maxBytes=1_000_000, backupCount=5,
        )
        game_file.setLevel(logging.INFO)
        game_file.setFormatter(logging.Formatter("%(message)s"))  # message IS the JSON
        game_logger.addHandler(game_file)
    except OSError:
        pass

    # ── gameplay history — plain text, one readable line per game ───────
    history_logger = logging.getLogger("guesswho.games.txt")
    history_logger.setLevel(logging.INFO)
    history_logger.propagate = False

    if console:
        # Echo to console/stdout too — on a host like Northflank the
        # container's own log viewer captures stdout even if local disk
        # doesn't survive a restart or redeploy, so this is the one copy
        # you can always count on. Skipped for the windowed desktop
        # build, which has no console to write to.
        history_console = logging.StreamHandler()
        history_console.setLevel(logging.INFO)
        history_console.setFormatter(logging.Formatter("[GAME] %(message)s"))
        history_logger.addHandler(history_console)

    try:
        history_file = logging.handlers.RotatingFileHandler(
            GAME_HISTORY_PATH, maxBytes=1_000_000, backupCount=5,
        )
        history_file.setLevel(logging.INFO)
        history_file.setFormatter(logging.Formatter("%(message)s"))
        history_logger.addHandler(history_file)
    except OSError:
        pass


def _fmt_duration(seconds):
    if seconds is None:
        return "?"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _fmt_secrets(secrets):
    if not secrets:
        return None
    return "Secrets — " + " | ".join(f"{player}: {card}" for player, card in secrets.items())


def _fmt_transcript_1v1(transcript):
    """Turn the 1v1 question/answer list into indented transcript lines,
    numbering each question and nesting its answer underneath. NOTE: this
    can't show card eliminations or in-progress guesses — those happen
    entirely inside each player's own client and are never sent to the
    server at all, so there's nothing here to log."""
    lines = []
    qn = 0
    for entry in transcript:
        if entry.get("type") == "question":
            qn += 1
            lines.append(f"  Q{qn}. {entry.get('player', '?')} asked: \"{entry.get('text', '')}\"")
        elif entry.get("type") == "answer":
            yn = "YES" if entry.get("yes") else "NO"
            lines.append(f"      -> {entry.get('player', '?')} answered {yn}")
    return lines


def _fmt_transcript_imposter(transcript):
    """Turn the imposter round's descriptions into lines grouped by round."""
    lines = []
    current_round = None
    for entry in transcript:
        r = entry.get("round")
        if r != current_round:
            current_round = r
            lines.append(f"Round {r}")
        lines.append(f"  {entry.get('player', '?')} description: \"{entry.get('text', '')}\"")
    return lines


def _fmt_powers(powers):
    """One line per Imposter power-up used, in the order they happened."""
    return [
        f"  Round {p.get('round', '?')}: {p.get('player', '?')} used {p.get('label', p.get('power', '?'))} "
        f"({p.get('cost', '?')} pts) \u2014 {p.get('detail', '')}"
        for p in (powers or [])
    ]


def _fmt_roles(roles, members):
    """'Eve (imposter), Finn (innocent), Gus (innocent)' — in roster order,
    falling back to 'unknown' for anyone roles didn't have a role for."""
    return ", ".join(f"{m} ({roles.get(m, 'unknown')})" for m in members)


def _human_line(ts, event, f):
    """Render one gameplay event as a readable block — one line for a
    quick event, several lines (header, transcript, result) for a full
    finished or abandoned game."""
    if event == "match_end":
        a, b = f.get("players", ("?", "?"))
        lines = [
            "=" * 78,
            f"{ts} | 1v1 | {a} vs {b} | category: {f.get('category') or '?'} | "
            f"duration: {_fmt_duration(f.get('duration_sec'))}",
        ]
        secrets_line = _fmt_secrets(f.get("secrets"))
        if secrets_line:
            lines.append(secrets_line)
        lines.extend(_fmt_transcript_1v1(f.get("transcript", [])))
        lines.append(f"RESULT: {f.get('reported_by', '?')} reported {f.get('result', '?')} "
                     f"— {f.get('reason', '')}")
        lines.append("=" * 78)
        return "\n".join(lines)

    if event == "match_abandoned":
        a, b = f.get("players", ("?", "?"))
        lines = [
            "-" * 78,
            f"{ts} | 1v1 ABANDONED | {a} vs {b} | category: {f.get('category') or '?'} | "
            f"{f.get('left_by', '?')} left ({f.get('reason', 'left')}) | "
            f"duration: {_fmt_duration(f.get('duration_sec'))}",
        ]
        secrets_line = _fmt_secrets(f.get("secrets"))
        if secrets_line:
            lines.append(secrets_line)
        lines.extend(_fmt_transcript_1v1(f.get("transcript", [])))
        lines.append("-" * 78)
        return "\n".join(lines)

    if event == "imposter_match_end":
        members = f.get("members", [])
        roles = f.get("roles") or {}
        votes = f.get("votes") or {}
        winner = {"innocents": "Innocents",
                  "original_imposter": "Original Imposter (after a swap)"}.get(f.get("winner"), "Imposter")
        lines = [
            "=" * 78,
            f"{ts} | IMPOSTER | {len(members)} players | {', '.join(members)} | "
            f"category: {f.get('category') or '?'} | duration: {_fmt_duration(f.get('duration_sec'))}",
            _fmt_roles(roles, members),
            f"Imposter secret: {f.get('imposter_card', '?')} | Innocent secret: {f.get('real_card', '?')}",
        ]
        lines.extend(_fmt_transcript_imposter(f.get("transcript", [])))
        if f.get("powers"):
            lines.append("Powers used:")
            lines.extend(_fmt_powers(f["powers"]))
        lines.append("Who's the Imposter?")
        for voter, accused in votes.items():
            lines.append(f"  {voter} voted {accused}")
        if f.get("winner") == "original_imposter":
            lines.append(f"WINNER: {winner} \u2014 {f.get('original_imposter', '?')} was voted out, "
                         f"but the Imposter title had been swapped onto {f.get('imposter', '?')}")
        else:
            lines.append(f"WINNER: {winner} ({f.get('imposter', '?')} was "
                         f"{'caught' if f.get('caught') else 'not caught'})")
        lines.append("=" * 78)
        return "\n".join(lines)

    if event == "imposter_match_abandoned":
        members = f.get("members", [])
        roles = f.get("roles") or {}
        lines = [
            "-" * 78,
            f"{ts} | IMPOSTER ABANDONED | {len(members)} players | {', '.join(members)} | "
            f"category: {f.get('category') or '?'} | "
            f"{f.get('last_to_leave', '?')} was last to leave | "
            f"duration: {_fmt_duration(f.get('duration_sec'))}",
        ]
        if roles:
            lines.append(_fmt_roles(roles, members))
        if f.get("real_card"):
            lines.append(f"Imposter secret: {f.get('imposter_card', '?')} | Innocent secret: {f.get('real_card', '?')}")
        lines.extend(_fmt_transcript_imposter(f.get("transcript", [])))
        if f.get("powers"):
            lines.append("Powers used:")
            lines.extend(_fmt_powers(f["powers"]))
        lines.append("-" * 78)
        return "\n".join(lines)

    if event == "bot_match_end":
        return (f"{ts} | {f.get('player', '?')} vs Bot | category: {f.get('category') or '?'} | "
                f"result: {f.get('result', '?')} ({f.get('reason', '')}) | "
                f"duration: {_fmt_duration(f.get('duration_sec'))} | "
                f"questions asked: {f.get('questions_asked', '?')}")

    # fallback, so a future event type without a dedicated format still
    # shows up instead of silently being dropped
    extras = ", ".join(f"{k}={v}" for k, v in f.items())
    return f"{ts} | {event} | {extras}"


def log_event(event, **fields):
    """Write one gameplay event, e.g.:

        log_event("match_end", players=("Alice", "Bob"), result="WIN",
                   category="fruits", duration_sec=142.3,
                   secrets={"Alice": "Apple", "Bob": "Banana"},
                   transcript=[{"type": "question", "player": "Alice", "text": "..."},
                               {"type": "answer", "player": "Bob", "yes": True}, ...])

    This writes TWO copies: a JSON object to gameplay.log (for later
    analysis — every field passed in rides along as-is) and a readable
    block to game_history.txt and the console, if enabled (for just
    reading what happened).
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    record = {"ts": ts, "event": event, **fields}
    logging.getLogger("guesswho.games").info(json.dumps(record))

    logging.getLogger("guesswho.games.txt").info(_human_line(ts, event, fields))