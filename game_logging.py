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


def _human_line(ts, event, f):
    """Render one gameplay event as a single plain-English line."""
    if event == "match_end":
        a, b = f.get("players", ("?", "?"))
        return (f"{ts} | {a} vs {b} | category: {f.get('category') or '?'} | "
                f"{f.get('reported_by', '?')} reported {f.get('result', '?')} "
                f"({f.get('reason', '')}) | duration: {_fmt_duration(f.get('duration_sec'))} | "
                f"questions asked: {f.get('questions_asked', '?')}")

    if event == "match_abandoned":
        a, b = f.get("players", ("?", "?"))
        return (f"{ts} | {a} vs {b} | category: {f.get('category') or '?'} | "
                f"ABANDONED — {f.get('left_by', '?')} ({f.get('reason', 'left')}) | "
                f"duration: {_fmt_duration(f.get('duration_sec'))} | "
                f"questions asked: {f.get('questions_asked', '?')}")

    if event == "imposter_match_end":
        members = ", ".join(f.get("members", []))
        caught = "YES" if f.get("caught") else "NO"
        return (f"{ts} | Imposter room {f.get('room_id', '?')} | players: {members} | "
                f"category: {f.get('category') or '?'} | imposter: {f.get('imposter', '?')} | "
                f"caught: {caught} | duration: {_fmt_duration(f.get('duration_sec'))}")

    if event == "imposter_match_abandoned":
        return (f"{ts} | Imposter room {f.get('room_id', '?')} | "
                f"category: {f.get('category') or '?'} | "
                f"ABANDONED — {f.get('last_to_leave', '?')} was last to leave | "
                f"duration: {_fmt_duration(f.get('duration_sec'))}")

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
                   category="fruits", duration_sec=142.3, questions_asked=6)

    This writes TWO copies: a JSON line to gameplay.log (for later
    analysis) and a plain-English line to game_history.txt and the
    console, if enabled (for just reading what happened).
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    record = {"ts": ts, "event": event, **fields}
    logging.getLogger("guesswho.games").info(json.dumps(record))

    logging.getLogger("guesswho.games.txt").info(_human_line(ts, event, fields))