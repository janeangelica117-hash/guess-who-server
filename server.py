import os
import random
import uuid
import sqlite3
import time as _time
from urllib.parse import quote
from flask import Flask, request, send_file, abort
from flask_socketio import SocketIO, emit

from game_logging import setup_logging, log_event, GAME_HISTORY_PATH, GAMEPLAY_JSON_PATH
import logging

try:
    import game_history_view     # the picture version of the game history page
except Exception:                # file wasn't deployed — plain-text history still works
    game_history_view = None

try:
    # Pure-data module (no pygame) — the server only needs it to pick the
    # random decoy card offered by the Imposter's "new secret" power.
    from categories import get_cards as _get_category_cards
except Exception:   # categories.py / its card files weren't deployed
    _get_category_cards = None

setup_logging()
logger = logging.getLogger("guesswho")

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Set this as an environment variable on Northflank (Service -> Environment)
# to view/download logs/game_history.txt at /admin/game-history?key=...
# Left unset, the route is disabled — no key means no access, not open access.
ADMIN_KEY = os.environ.get("ADMIN_KEY")


@app.route("/admin/game-history")
def admin_game_history():
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(403)
    if not os.path.exists(GAME_HISTORY_PATH) or os.path.getsize(GAME_HISTORY_PATH) == 0:
        # The log file gets created the instant the server starts (before
        # any game is ever played), so checking existence alone isn't
        # enough — it's always "there", just empty until a real game ends.
        return "No games recorded yet.", 200, {"Content-Type": "text/plain"}
    # as_attachment=False so it opens right in the browser tab (readable);
    # add ?download=1 to save it as a file instead.
    as_attachment = request.args.get("download") == "1"
    return send_file(GAME_HISTORY_PATH, mimetype="text/plain", as_attachment=as_attachment)


@app.route("/admin/game-history/view")
def admin_game_history_view():
    """Same history, but as a web page with the actual card pictures.
    ?limit=N shows the last N games (default 100, max 500)."""
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(403)
    if game_history_view is None:
        return "game_history_view.py isn't deployed on this server.", 503, {"Content-Type": "text/plain"}
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100
    events = game_history_view.read_events(GAMEPLAY_JSON_PATH, limit)
    page = game_history_view.render_page(
        events,
        game_history_view.server_image_src(ADMIN_KEY),
        plain_text_url=f"/admin/game-history?key={quote(ADMIN_KEY, safe='')}",
        limit_note=f" (last {limit} at most)",
    )
    return page, 200, {"Content-Type": "text/html; charset=utf-8", "Referrer-Policy": "no-referrer"}


@app.route("/admin/card-image/<category>/<path:card_name>")
def admin_card_image(category, card_name):
    """One card's picture, looked up by category + card NAME from the game's
    own card lists (never by a file path from the URL), so it can only ever
    serve card art."""
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(403)
    path = game_history_view.card_image_path(category, card_name) if game_history_view else None
    if not path:
        abort(404)
    resp = send_file(path)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


# { socket_id: username }
players = {}

# { socket_id: partner_socket_id }
matches = {}

# { socket_id: True } — tracks who is the host of their match
hosts = {}

# { frozenset({sid_a, sid_b}): {"players": (name_a, name_b), "category": str|None,
#   "started_at": float|None, "questions": int} } — per-1v1-match info that
# exists purely for gameplay logging (see log_event calls below); has no
# effect on how the match is actually played.
match_meta = {}

# ── Accounts: persistent identity, points, and usernames ───────────────────
# Keyed by a device_id the client generates once and keeps locally (see
# main.py) rather than by socket id, since sockets don't survive a
# reconnect. google_id sits ready and unused for now — wiring up real
# Google Sign-In later means filling this column in during on_identify,
# nothing else about the schema or the rest of this flow has to change.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.db")
WIN_POINTS  = 5
RENAME_COST = 20


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                device_id        TEXT PRIMARY KEY,
                google_id        TEXT UNIQUE,
                username         TEXT UNIQUE NOT NULL,
                points           INTEGER NOT NULL DEFAULT 0,
                has_set_username INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT NOT NULL
            )
        """)


_init_db()

# { socket_id: device_id } — who to credit when a game this socket is
# playing in ends. Populated by on_identify, cleared on disconnect.
device_ids = {}

# { frozenset({sid_a, sid_b}): {"sid": claimant_sid, "result": "WIN"/"LOSE"/"FORFEIT"} }
# A 1v1 game_over is one client's self-report, so it sits here until the
# other client's own ack corroborates (or contradicts) it — see
# _resolve_1v1_points. Imposter mode doesn't need this: the server already
# decides who got caught on its own.
pending_game_results = {}


def _unique_account_username(base):
    base = (base or "Player").strip() or "Player"
    with _db() as conn:
        candidate, n = base, 2
        while conn.execute("SELECT 1 FROM accounts WHERE username = ?", (candidate,)).fetchone():
            candidate = f"{base}{n}"
            n += 1
        return candidate


def _get_or_create_account(device_id):
    with _db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE device_id = ?", (device_id,)).fetchone()
        if row:
            return dict(row)
        username = _unique_account_username("Player")
        conn.execute(
            "INSERT INTO accounts (device_id, username, points, has_set_username, created_at) "
            "VALUES (?, ?, 0, 0, ?)",
            (device_id, username, _time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM accounts WHERE device_id = ?", (device_id,)).fetchone())


def _award_points(device_id, amount):
    if not device_id or not amount:
        return
    with _db() as conn:
        conn.execute("UPDATE accounts SET points = points + ? WHERE device_id = ?", (amount, device_id))
        conn.commit()


def _resolve_1v1_points(sid_a, result_a, sid_b, result_b):
    """Award the win only when both sides' self-reported outcomes are
    consistent with each other. A single modified client can no longer
    farm points for free — the untouched opponent's client will report
    the opposite outcome, and anything that doesn't cleanly resolve to
    exactly one winner is left unresolved rather than guessed at."""
    pair = {result_a, result_b}
    winner_sid = None
    if pair == {"WIN", "LOSE"}:
        winner_sid = sid_a if result_a == "WIN" else sid_b
    elif "FORFEIT" in pair and pair != {"FORFEIT"}:
        winner_sid = sid_a if result_a != "FORFEIT" else sid_b
    if winner_sid:
        _award_points(device_ids.get(winner_sid), WIN_POINTS)

# ── Imposter mode: separate room-based system (3-10 players), running
# alongside the 1v1 matches above rather than replacing them ───────────────

# { room_id: {
#     host, members (list, join order = turn order source), category,
#     started, secret_card, imposter_sid, imposter_card,
#     round (0=lobby, 1-3=describing, 4=voting, 5=result),
#     turn_order, turn_idx, votes {voter_sid: accused_sid}
# } }
imposter_rooms = {}

# { socket_id: room_id } — reverse lookup for whichever room a player is in
player_room = {}

# ── Imposter power-ups ─────────────────────────────────────────────────────────
# Everyone gets IMPOSTER_START_POINTS at the start of a game. Only whoever
# currently holds the Imposter title can spend them, and each power can be
# used once per game, during the describing rounds only. (These are per-game
# "power points" — separate from the persistent account points in the DB.)
IMPOSTER_START_POINTS = 50
IMPOSTER_POWER_COSTS  = {"swap": 25, "choose": 10, "match": 50}
IMPOSTER_POWER_LABELS = {"swap": "SWAP ROLE", "choose": "NEW SECRET", "match": "COPY CARD"}


def broadcast_players():
    """Send each client the full player list with availability status."""
    for sid in players:
        others = []
        for s, u in players.items():
            if s == sid:
                continue
            status = "busy" if (s in matches or (s in player_room and imposter_rooms.get(player_room[s], {}).get("started"))) else "available"
            others.append({"username": u, "status": status})
        socketio.emit("update_players", others, to=sid)


@socketio.on("ping_keepalive")
def on_ping_keepalive(data):
    """Client keepalive ping — just acknowledge silently."""
    pass


@socketio.on("join")
def on_join(data):
    username = str(data.get("username", "")).strip()
    if not username:
        return
    players[request.sid] = username
    logger.info(f"{username} joined (sid={request.sid})")
    broadcast_players()


@socketio.on("identify")
def on_identify(data):
    """First thing a client does after connecting: exchange its locally
    persisted device_id for a real account (points + username), creating
    one on first contact. This is the seam Google Sign-In slots into
    later — swap this lookup for a verified Google account id and nothing
    else about the rest of this flow has to change."""
    device_id = str(data.get("device_id", "")).strip()
    if not device_id:
        return
    device_ids[request.sid] = device_id
    account = _get_or_create_account(device_id)
    # The socket already joined under a throwaway default name (see
    # main.py) before this account lookup could complete — now that we
    # know the persisted one, make the "who's online" list reflect it too.
    if request.sid in players and players[request.sid] != account["username"]:
        players[request.sid] = account["username"]
        broadcast_players()
    emit("identify_result", {
        "username": account["username"],
        "points": account["points"],
        "has_set_username": bool(account["has_set_username"]),
        "rename_cost": RENAME_COST,
    })


@socketio.on("set_username")
def on_set_username(data):
    device_id = device_ids.get(request.sid, "")
    if not device_id:
        emit("set_username_result", {"ok": False, "reason": "Not identified yet."})
        return
    new_name = str(data.get("username", "")).strip()[:20]
    if not new_name:
        emit("set_username_result", {"ok": False, "reason": "Enter a name."})
        return

    with _db() as conn:
        account = conn.execute("SELECT * FROM accounts WHERE device_id = ?", (device_id,)).fetchone()
        if not account:
            emit("set_username_result", {"ok": False, "reason": "Account not found."})
            return
        if conn.execute(
            "SELECT 1 FROM accounts WHERE username = ? AND device_id != ?", (new_name, device_id)
        ).fetchone():
            emit("set_username_result", {"ok": False, "reason": "That name is taken."})
            return

        first_time = not account["has_set_username"]
        if first_time:
            conn.execute(
                "UPDATE accounts SET username = ?, has_set_username = 1 WHERE device_id = ?",
                (new_name, device_id),
            )
        else:
            if account["points"] < RENAME_COST:
                emit("set_username_result", {
                    "ok": False,
                    "reason": f"Need {RENAME_COST} points to change your name.",
                    "points": account["points"],
                })
                return
            conn.execute(
                "UPDATE accounts SET username = ?, points = points - ? WHERE device_id = ?",
                (new_name, RENAME_COST, device_id),
            )
        conn.commit()
        account = dict(conn.execute("SELECT * FROM accounts WHERE device_id = ?", (device_id,)).fetchone())

    # Keep the ephemeral "who's online" name in sync too, so the Friends
    # list and any room reflect the change right away.
    players[request.sid] = new_name
    broadcast_players()
    emit("set_username_result", {"ok": True, "username": new_name, "points": account["points"]})


@socketio.on("invite")
def on_invite(data):
    target_username = str(data.get("target", "")).strip()
    sender_username = players.get(request.sid, "")

    target_sid = next(
        (s for s, u in players.items() if u == target_username),
        None
    )

    if not target_sid:
        emit("invite_response", {"accepted": False, "reason": "Player not available."})
        return

    socketio.emit("incoming_invite", {"from": sender_username}, to=target_sid)
    socketio.emit("invite_pending",  {"to": target_username},   to=request.sid)


@socketio.on("invite_accept")
def on_invite_accept(data):
    sender_username = str(data.get("from", "")).strip()
    accepter_sid = request.sid
    accepter_username = players.get(accepter_sid, "")

    sender_sid = next(
        (s for s, u in players.items() if u == sender_username),
        None
    )

    if not sender_sid:
        return

    matches[sender_sid] = accepter_sid
    matches[accepter_sid] = sender_sid

    # Sender is the host
    hosts[sender_sid] = True

    match_meta[frozenset((sender_sid, accepter_sid))] = {
        "players": (sender_username, accepter_username),
        "category": "desserts",  # the client's own default when nobody touches the picker
        "started_at": None,
        "secrets": {},      # {username: secret card name}
        "transcript": [],   # [{"type": "question"/"answer", "player": username, ...}]
    }

    socketio.emit("matched", {"opponent": accepter_username, "is_host": True},  to=sender_sid)
    socketio.emit("matched", {"opponent": sender_username,   "is_host": False}, to=accepter_sid)

    logger.info(f"match formed: {sender_username} (host) <-> {accepter_username}")
    broadcast_players()


@socketio.on("invite_decline")
def on_invite_decline(data):
    sender_username = str(data.get("from", "")).strip()
    decliner_username = players.get(request.sid, "")

    sender_sid = next(
        (s for s, u in players.items() if u == sender_username),
        None
    )
    if sender_sid:
        socketio.emit("invite_declined", {"by": decliner_username}, to=sender_sid)


@socketio.on("leave_match")
def on_leave_match(data):
    """Either player signals they are leaving the match (not disconnecting)."""
    leaver_sid = request.sid
    partner_sid = matches.get(leaver_sid)

    # Clean up match and host records for both players
    matches.pop(leaver_sid,  None)
    hosts.pop(leaver_sid,    None)
    if partner_sid:
        matches.pop(partner_sid, None)
        hosts.pop(partner_sid,   None)
        # Tell the partner to return to lobby
        socketio.emit("partner_left_match", {}, to=partner_sid)

    meta = match_meta.pop(frozenset((leaver_sid, partner_sid)), None) if partner_sid else None
    if meta and meta["started_at"]:
        # They left after the game actually started, not just lobby chit-chat —
        # worth knowing how often that happens vs. a clean game_over.
        log_event(
            "match_abandoned", players=meta["players"], category=meta["category"],
            left_by=players.get(leaver_sid, "?"), reason="left_match",
            duration_sec=round(_time.time() - meta["started_at"], 1),
            secrets=meta["secrets"], transcript=meta["transcript"],
        )

    logger.info(f"{players.get(leaver_sid, '?')} left the match")
    broadcast_players()


@socketio.on("kick")
def on_kick(data):
    """Host kicks their matched partner."""
    kicker_sid = request.sid
    kicker_username = players.get(kicker_sid, "")

    # Only hosts can kick
    if kicker_sid not in hosts:
        return

    partner_sid = matches.get(kicker_sid)
    if not partner_sid:
        return

    partner_username = players.get(partner_sid, "unknown")

    # Remove match
    matches.pop(kicker_sid,   None)
    matches.pop(partner_sid,  None)
    hosts.pop(kicker_sid,     None)
    match_meta.pop(frozenset((kicker_sid, partner_sid)), None)

    # Notify kicked player
    socketio.emit("kicked", {"by": kicker_username}, to=partner_sid)
    # Notify host that kick succeeded
    socketio.emit("kick_success", {"player": partner_username}, to=kicker_sid)

    logger.info(f"{kicker_username} kicked {partner_username}")
    broadcast_players()


@socketio.on("game_start")
def on_game_start(data):
    """Host signals that the game is starting — relay to partner."""
    starter_sid = request.sid

    # Only hosts can start
    if starter_sid not in hosts:
        return

    partner_sid = matches.get(starter_sid)
    if not partner_sid:
        return

    starter_username = players.get(starter_sid, "")
    meta = match_meta.get(frozenset((starter_sid, partner_sid)))
    if meta:
        meta["started_at"] = _time.time()

    logger.info(f"{starter_username} started the game")
    socketio.emit("game_started", {}, to=partner_sid)


@socketio.on("first_turn")
def on_first_turn(data):
    """Host tells both players who goes first."""
    if request.sid not in hosts:
        return
    partner_sid = matches.get(request.sid)
    if not partner_sid:
        return
    host_goes_first = bool(data.get("host_goes_first", True))
    # tell partner the opposite
    socketio.emit("first_turn", {"your_turn": not host_goes_first}, to=partner_sid)


@socketio.on("secret")
def on_secret(data):
    """Relay a player's secret card name to their opponent."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        name = data.get("name", "")
        meta = match_meta.get(frozenset((request.sid, partner_sid)))
        if meta:
            meta["secrets"][players.get(request.sid, "?")] = name
        socketio.emit("secret", {"name": name}, to=partner_sid)


@socketio.on("question")
def on_question(data):
    """Relay a question from the asker to the answerer."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        text = data.get("text", "")
        meta = match_meta.get(frozenset((request.sid, partner_sid)))
        if meta:
            meta["transcript"].append({
                "type": "question", "player": players.get(request.sid, "?"), "text": text,
            })
        logger.debug(f"question {players.get(request.sid,'?')} -> {players.get(partner_sid,'?')}: {text!r}")
        socketio.emit("question", {
            "text":   data.get("text", ""),
            "secret": data.get("secret", ""),   # opponent's secret, piggybacked
        }, to=partner_sid)


@socketio.on("answer")
def on_answer(data):
    """Relay YES/NO answer back to the asker."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        yes = bool(data.get("yes", False))
        meta = match_meta.get(frozenset((request.sid, partner_sid)))
        if meta:
            meta["transcript"].append({
                "type": "answer", "player": players.get(request.sid, "?"), "yes": yes,
            })
        socketio.emit("answer", {
            "yes":    yes,
            "secret": data.get("secret", ""),   # opponent's secret, piggybacked
        }, to=partner_sid)


@socketio.on("end_turn")
def on_end_turn(data):
    """Player signals they finished their turn — notify partner it's their turn."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("your_turn", {"secret": data.get("secret", "")}, to=partner_sid)


@socketio.on("game_over")
def on_game_over(data):
    """Relay a game-over result to the partner, and stage it for the
    corroborated points check once the partner's own ack comes back (see
    _resolve_1v1_points) — the win itself isn't paid out here."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("game_over", {
            "result": data.get("result", ""),
            "reason": data.get("reason", ""),
            "secret": data.get("secret", ""),   # sender's secret dessert name
        }, to=partner_sid)
        pending_game_results[frozenset((request.sid, partner_sid))] = {
            "sid": request.sid, "result": data.get("result", ""),
        }

        meta = match_meta.pop(frozenset((request.sid, partner_sid)), None)
        log_event(
            "match_end",
            players=meta["players"] if meta else (players.get(request.sid, "?"), players.get(partner_sid, "?")),
            category=meta["category"] if meta else None,
            result=data.get("result", ""),
            reason=data.get("reason", ""),
            reported_by=players.get(request.sid, "?"),
            duration_sec=round(_time.time() - meta["started_at"], 1) if meta and meta["started_at"] else None,
            secrets=meta["secrets"] if meta else {},
            transcript=meta["transcript"] if meta else [],
        )


@socketio.on("game_over_ack")
def on_game_over_ack(data):
    """The receiving side's own view of how the game ended. Never
    re-relayed (the original game_over already told them the outcome) —
    used only so the server can compare both sides before paying out."""
    sid = request.sid
    key = next((k for k in pending_game_results if sid in k), None)
    if not key:
        return
    entry = pending_game_results.pop(key)
    if entry["sid"] == sid:
        return   # an ack should come from the OTHER side, not the original claimant
    _resolve_1v1_points(entry["sid"], entry["result"], sid, data.get("result", ""))


@socketio.on("final_chance")
def on_final_chance(data):
    """Relay: sender's own last-card deduction failed — give the partner
    their one guaranteed shot at the sender's secret."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("final_chance", {}, to=partner_sid)


@socketio.on("category_select")
def on_category_select(data):
    """Relay: host picked (or changed) the card category for this match."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        category = data.get("category", "desserts")
        meta = match_meta.get(frozenset((request.sid, partner_sid)))
        if meta:
            meta["category"] = category
        socketio.emit("category_select", {"category": category}, to=partner_sid)


@socketio.on("profile_data")
def on_profile_data(data):
    """Relay a player's profile to their matched partner."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("profile_data", data, to=partner_sid)


@socketio.on("chat_emoji")
def on_chat_emoji(data):
    """Relay an emoji reaction to the partner (shown on both screens)."""
    partner_sid = matches.get(request.sid)
    emoji = str(data.get("emoji", "")).strip()
    if partner_sid and emoji:
        socketio.emit("chat_emoji", {"emoji": emoji}, to=partner_sid)


@socketio.on("chat_message")
def on_chat_message(data):
    """Relay a free-text lobby chat message to the matched partner."""
    partner_sid = matches.get(request.sid)
    sender_username = players.get(request.sid, "")
    text = str(data.get("text", "")).strip()[:300]
    if partner_sid and text:
        socketio.emit("chat_message", {
            "from": sender_username,
            "text": text,
        }, to=partner_sid)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    username = players.get(sid, "unknown")

    # Do this before anything below removes sid from players/device_ids —
    # _imposter_remove_player can trigger _imposter_resolve_vote (if this
    # disconnect is what completes the vote), which needs both still
    # intact to report the right username and award points correctly.
    _imposter_remove_player(sid)

    players.pop(sid, None)
    partner_sid = matches.pop(sid, None)
    hosts.pop(sid, None)
    device_ids.pop(sid, None)
    for key in [k for k in pending_game_results if sid in k]:
        pending_game_results.pop(key, None)   # no ack is coming now — leave it unresolved

    if partner_sid:
        matches.pop(partner_sid, None)
        hosts.pop(partner_sid,   None)
        socketio.emit("opponent_left", {}, to=partner_sid)

        meta = match_meta.pop(frozenset((sid, partner_sid)), None)
        if meta and meta["started_at"]:
            log_event(
                "match_abandoned", players=meta["players"], category=meta["category"],
                left_by=username, reason="disconnect",
                duration_sec=round(_time.time() - meta["started_at"], 1),
                secrets=meta["secrets"], transcript=meta["transcript"],
            )

    logger.info(f"{username} left (sid={sid})")
    broadcast_players()


# ── Imposter mode ────────────────────────────────────────────────────────────

def _imposter_room_broadcast(room_id, event, data):
    room = imposter_rooms.get(room_id)
    if not room:
        return
    for sid in room["members"]:
        socketio.emit(event, data, to=sid)


def _imposter_room_public_state(room_id):
    room = imposter_rooms[room_id]
    return {
        "room_id":  room_id,
        "host":     players.get(room["host"], ""),
        "members":  [players.get(s, "?") for s in room["members"]],
        "category": room["category"],
    }


def _imposter_remove_player(sid):
    """Shared cleanup for both an explicit leave and a disconnect."""
    room_id = player_room.pop(sid, None)
    if not room_id:
        return
    room = imposter_rooms.get(room_id)
    if not room:
        return
    if sid in room["members"]:
        room["members"].remove(sid)
    if not room["members"]:
        if room["started"] and room["round"] != 5:
            # Room emptied out mid-round — nobody ever got a result. Use the
            # frozen original_members, not room["members"] (already emptied
            # by the removals above), so the log still shows who was playing.
            roster = room.get("original_members") or []
            names  = room.get("original_names") or {}
            roles = {
                names.get(s, "?"): ("imposter" if s == room["imposter_sid"] else "innocent")
                for s in roster
            }
            log_event(
                "imposter_match_abandoned", room_id=room_id, category=room["category"],
                members=[names.get(s, "?") for s in roster],
                roles=roles,
                real_card=room["secret_card"], imposter_card=room["imposter_card"],
                last_to_leave=names.get(sid, players.get(sid, "?")),
                duration_sec=round(_time.time() - room["started_at"], 1) if room.get("started_at") else None,
                transcript=room["transcript"],
                powers=room.get("power_log", []),
            )
        imposter_rooms.pop(room_id, None)
        return
    if room["host"] == sid:
        room["host"] = room["members"][0]   # promote the next-longest member
    if room["started"] and sid in room.get("turn_order", []):
        # A player leaving mid-game shouldn't freeze everyone else's turn —
        # just drop them from the turn order; round/turn_idx logic below
        # already advances by index, so this keeps it self-consistent.
        idx = room["turn_order"].index(sid)
        room["turn_order"].remove(sid)
        if idx < room["turn_idx"]:
            room["turn_idx"] -= 1
    if room["round"] == 4 and len(room["votes"]) >= len(room["members"]):
        # Someone left mid-vote without ever casting one — the denominator
        # just shrank to match what's already been cast, which is what was
        # actually leaving everyone else stuck on "waiting on the room".
        _imposter_resolve_vote(room_id)
        return
    _imposter_room_broadcast(room_id, "imposter_room_state", _imposter_room_public_state(room_id))


@socketio.on("imposter_create_room")
def on_imposter_create_room(data):
    sid = request.sid
    if sid in player_room:
        return
    room_id = uuid.uuid4().hex[:8]
    imposter_rooms[room_id] = {
        "host": sid, "members": [sid], "category": "desserts",
        "started": False, "secret_card": None, "imposter_sid": None,
        "imposter_card": None, "round": 0, "turn_order": [], "turn_idx": 0,
        "votes": {}, "started_at": None, "transcript": [],
        "original_members": [], "original_names": {},
    }
    imposter_rooms[room_id].update(_imposter_blank_power_state())
    player_room[sid] = room_id
    socketio.emit("imposter_room_state", _imposter_room_public_state(room_id), to=sid)
    broadcast_players()


@socketio.on("imposter_invite")
def on_imposter_invite(data):
    """Any member of a room can invite any other available player in —
    not host-only, unlike starting the game."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["started"] or len(room["members"]) >= 10:
        return

    target_username = str(data.get("target", "")).strip()
    target_sid = next((s for s, u in players.items() if u == target_username), None)
    if not target_sid or target_sid in player_room or target_sid in matches:
        socketio.emit("imposter_invite_response",
                       {"accepted": False, "reason": "Player not available."}, to=sid)
        return

    socketio.emit("imposter_incoming_invite", {
        "from": players.get(sid, ""), "room_id": room_id,
    }, to=target_sid)


@socketio.on("imposter_invite_accept")
def on_imposter_invite_accept(data):
    sid = request.sid
    room_id = str(data.get("room_id", ""))
    room = imposter_rooms.get(room_id)
    if not room or room["started"] or len(room["members"]) >= 10 or sid in player_room:
        return
    room["members"].append(sid)
    player_room[sid] = room_id
    _imposter_room_broadcast(room_id, "imposter_room_state", _imposter_room_public_state(room_id))
    broadcast_players()


@socketio.on("imposter_invite_decline")
def on_imposter_invite_decline(data):
    sender_username = str(data.get("from", "")).strip()
    sender_sid = next((s for s, u in players.items() if u == sender_username), None)
    if sender_sid:
        socketio.emit("imposter_invite_declined", {"by": players.get(request.sid, "")}, to=sender_sid)


@socketio.on("imposter_leave_room")
def on_imposter_leave_room(data):
    _imposter_remove_player(request.sid)
    broadcast_players()


@socketio.on("imposter_kick")
def on_imposter_kick(data):
    """Host removes a member from the lobby (pre-game only)."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["host"] != sid or room["started"]:
        return
    target_username = str(data.get("target", "")).strip()
    target_sid = next((s for s in room["members"] if players.get(s) == target_username), None)
    if not target_sid or target_sid == sid:
        return
    _imposter_remove_player(target_sid)
    socketio.emit("imposter_kicked", {"by": players.get(sid, "")}, to=target_sid)
    broadcast_players()


@socketio.on("imposter_category_select")
def on_imposter_category_select(data):
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["host"] != sid or room["started"]:
        return
    room["category"] = str(data.get("category", "desserts")).strip() or "desserts"
    _imposter_room_broadcast(room_id, "imposter_room_state", _imposter_room_public_state(room_id))


@socketio.on("imposter_chat_message")
def on_imposter_chat_message(data):
    """Free-text lobby chat, relayed to every member of the room (mirrors
    the 1v1 game's chat_message, just broadcast instead of 1-to-1)."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room:
        return
    text = str(data.get("text", "")).strip()[:300]
    if not text:
        return
    _imposter_room_broadcast(room_id, "imposter_chat_message", {
        "from": players.get(sid, ""), "text": text,
    })


@socketio.on("imposter_chat_emoji")
def on_imposter_chat_emoji(data):
    """Emoji reaction, relayed to every member of the room."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room:
        return
    emoji = str(data.get("emoji", "")).strip()
    if not emoji:
        return
    _imposter_room_broadcast(room_id, "imposter_chat_emoji", {
        "from": players.get(sid, ""), "emoji": emoji,
    })


@socketio.on("imposter_profile_data")
def on_imposter_profile_data(data):
    """Broadcast a player's avatar/profile to every other member of their
    room, so real avatars can render for everyone in the Multiplayer Lobby
    grid, not just yourself. Mirrors the 1v1 game's profile_data relay,
    just to the whole room instead of a single matched partner."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room:
        return
    payload = dict(data)
    payload["from"] = players.get(sid, "")
    _imposter_room_broadcast(room_id, "imposter_profile_data", payload)


@socketio.on("imposter_start_game")
def on_imposter_start_game(data):
    """Host only. Needs 3-10 members. The two card names (the real one
    everyone-but-the-imposter gets, and the different one the imposter
    gets) come from the host's client, same trust model as the 1v1 game's
    'secret' event — the server never needs to know real card data, only
    who gets matched with who."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["host"] != sid or room["started"]:
        return
    if not (3 <= len(room["members"]) <= 10):
        socketio.emit("imposter_start_failed", {"reason": "Need 3 to 10 players to start."}, to=sid)
        return

    cards = data.get("cards") or {}
    real_card     = str(cards.get("real", "")).strip()
    imposter_card = str(cards.get("imposter", "")).strip()
    if not real_card or not imposter_card or real_card == imposter_card:
        return

    members = list(room["members"])
    imposter_sid = random.choice(members)
    turn_order = members[:]
    random.shuffle(turn_order)

    room.update({
        "started": True, "secret_card": real_card, "imposter_sid": imposter_sid,
        "imposter_card": imposter_card, "round": 1, "turn_order": turn_order,
        "turn_idx": 0, "votes": {}, "started_at": _time.time(),
        # Frozen roster for logging. "members" shrinks as people leave, and if
        # several people disconnect in the same cascade (room emptying out),
        # players.get(sid) for the earlier ones is ALREADY gone by the time
        # the last disconnect triggers the abandoned-match log — so names
        # need to be captured now, not resolved later.
        "original_members": members,
        "original_names": {s: players.get(s, "?") for s in members},
        # ── power-up state ──
        # original_imposter_sid never changes; imposter_sid moves if someone
        # uses SWAP ROLE. player_cards is what each player is CURRENTLY
        # looking at (the imposter's can change mid-game).
        "original_imposter_sid": imposter_sid,
        "player_cards": {s: (imposter_card if s == imposter_sid else real_card) for s in members},
        "points": {s: IMPOSTER_START_POINTS for s in members},
        "powers_used": {s: set() for s in members},
        "pending_choices": {},
        "power_log": [],
    })

    for m_sid in members:
        socketio.emit("imposter_game_started", {
            "your_card":  imposter_card if m_sid == imposter_sid else real_card,
            "is_imposter": (m_sid == imposter_sid),
            "turn_order": [players.get(s, "?") for s in turn_order],
            "category":   room["category"],
            "points":     IMPOSTER_START_POINTS,
        }, to=m_sid)

    logger.info(f"imposter room {room_id} started: {len(members)} players, imposter is {players.get(imposter_sid)}")
    _imposter_announce_turn(room_id)


def _imposter_announce_turn(room_id):
    room = imposter_rooms[room_id]
    current_sid = room["turn_order"][room["turn_idx"]]
    _imposter_room_broadcast(room_id, "imposter_turn", {
        "player": players.get(current_sid, "?"),
        "round":  room["round"],
    })


@socketio.on("imposter_description")
def on_imposter_description(data):
    """Current describer submits their line for this round — relayed to
    the room, then advances to the next player, next round, or (after
    round 3) into voting."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or not room["started"] or room["round"] > 3:
        return
    if not room["turn_order"] or room["turn_order"][room["turn_idx"]] != sid:
        return   # not this player's turn

    text = str(data.get("text", "")).strip()[:200]
    if not text:
        return

    room["transcript"].append({
        "round": room["round"], "player": players.get(sid, "?"), "text": text,
    })
    _imposter_room_broadcast(room_id, "imposter_description", {
        "player": players.get(sid, "?"), "text": text, "round": room["round"],
    })

    room["turn_idx"] += 1
    if room["turn_idx"] >= len(room["turn_order"]):
        room["turn_idx"] = 0
        room["round"] += 1
        if room["round"] > 3:
            room["round"] = 4
            _imposter_room_broadcast(room_id, "imposter_voting_start", {
                "players": [players.get(s, "?") for s in room["members"]],
            })
            return
    _imposter_announce_turn(room_id)


@socketio.on("imposter_vote")
def on_imposter_vote(data):
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["round"] != 4 or sid in room["votes"]:
        return
    accused_username = str(data.get("accused", "")).strip()
    accused_sid = next((s for s in room["members"] if players.get(s) == accused_username), None)
    if not accused_sid:
        return
    room["votes"][sid] = accused_sid

    if len(room["votes"]) >= len(room["members"]):
        _imposter_resolve_vote(room_id)


def _imposter_resolve_vote(room_id):
    room = imposter_rooms[room_id]
    tally = {}
    for accused_sid in room["votes"].values():
        tally[accused_sid] = tally.get(accused_sid, 0) + 1
    top_count = max(tally.values())
    top_sids  = [s for s, c in tally.items() if c == top_count]
    top_sid   = top_sids[0] if len(top_sids) == 1 else None

    # Server-decided outcome, unlike 1v1's self-reported one — safe to pay
    # out directly. See _imposter_decide_outcome for who wins in each case.
    outcome, winners = _imposter_decide_outcome(room, top_sid)
    caught = (outcome == "caught")
    for sid in winners:
        _award_points(device_ids.get(sid), WIN_POINTS)

    original_sid  = room.get("original_imposter_sid") or room["imposter_sid"]
    original_name = room.get("original_names", {}).get(original_sid) or players.get(original_sid, "?")

    room["round"] = 5
    _imposter_room_broadcast(room_id, "imposter_result", {
        "caught":    caught,
        "outcome":   outcome,    # "caught" | "swap_win" | "escaped"
        "imposter":  players.get(room["imposter_sid"], "?"),
        "swapped":   original_sid != room["imposter_sid"],
        "original_imposter": original_name,
        "real_card": room["secret_card"],
        "votes":     {players.get(v, "?"): players.get(a, "?") for v, a in room["votes"].items()},
    })

    roster = room.get("original_members") or room["members"]
    names  = room.get("original_names") or {}
    roles = {
        names.get(s, "?"): ("imposter" if s == room["imposter_sid"] else "innocent")
        for s in roster
    }
    log_event(
        "imposter_match_end",
        room_id=room_id,
        members=[names.get(s, "?") for s in roster],
        category=room["category"],
        roles=roles,
        imposter=names.get(room["imposter_sid"], "?"),
        real_card=room["secret_card"],
        imposter_card=room["imposter_card"],
        caught=caught,
        winner={"caught": "innocents", "swap_win": "original_imposter"}.get(outcome, "imposter"),
        outcome=outcome,
        original_imposter=original_name,
        powers=room.get("power_log", []),
        votes={names.get(v, "?"): names.get(a, "?") for v, a in room["votes"].items()},
        transcript=room["transcript"],
        duration_sec=round(_time.time() - room["started_at"], 1) if room.get("started_at") else None,
    )


# ── Imposter power-ups ───────────────────────────────────────────────────────
# The server owns all of this (points, cards, who holds the title). Clients
# only ask for a power and get told the result, so nobody can edit their own
# points or card from the outside.

def _imposter_blank_power_state():
    return {
        "original_imposter_sid": None,
        "player_cards":    {},    # sid -> card name that player currently sees
        "points":          {},    # sid -> remaining power points
        "powers_used":     {},    # sid -> set of power keys already used
        "pending_choices": {},    # sid -> the two cards offered by NEW SECRET
        "power_log":       [],    # for game_history.txt / gameplay.log
    }


def _imposter_send_role_update(room, sid, message=""):
    """Tell one player their current role / card / points. Used after any
    power that changes something for them."""
    socketio.emit("imposter_role_update", {
        "is_imposter": sid == room["imposter_sid"],
        "your_card":   room["player_cards"].get(sid, ""),
        "points":      room["points"].get(sid, 0),
        "powers_used": sorted(room["powers_used"].get(sid, set())),
        "message":     message,
    }, to=sid)


def _imposter_power_denied(sid, reason):
    socketio.emit("imposter_power_denied", {"reason": reason}, to=sid)


def _imposter_power_check(sid, power):
    """Shared gatekeeping for every power. Returns the room if `sid` may use
    `power` right now, otherwise tells them why and returns None."""
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or not room["started"] or room["round"] not in (1, 2, 3):
        _imposter_power_denied(sid, "Powers only work while everyone is describing.")
        return None
    if sid != room["imposter_sid"]:
        _imposter_power_denied(sid, "Only the Imposter can use powers.")
        return None
    if power in room["powers_used"].get(sid, set()):
        _imposter_power_denied(sid, "You already used that power this game.")
        return None
    cost = IMPOSTER_POWER_COSTS[power]
    if room["points"].get(sid, 0) < cost:
        _imposter_power_denied(sid, f"Not enough points - that one costs {cost}.")
        return None
    return room


def _imposter_spend(room, sid, power):
    room["points"][sid] = room["points"].get(sid, 0) - IMPOSTER_POWER_COSTS[power]
    room["powers_used"].setdefault(sid, set()).add(power)
    room["pending_choices"].pop(sid, None)   # their card is about to change


def _imposter_log_power(room, sid, power, detail):
    room["power_log"].append({
        "round":  room["round"],
        "player": players.get(sid, "?"),
        "power":  power,
        "label":  IMPOSTER_POWER_LABELS[power],
        "cost":   IMPOSTER_POWER_COSTS[power],
        "detail": detail,
    })


def _imposter_decide_outcome(room, top_sid):
    """Who won? `top_sid` is the single most-voted player, or None on a tie.

    current  = whoever holds the Imposter title right now
    original = whoever was dealt the Imposter card at the start
    They're the same person unless someone used SWAP ROLE.

      * current is voted out            -> "caught": everyone except current wins
                                          (that includes the original imposter
                                          after a swap — they're an innocent now)
      * swapped, and ORIGINAL is voted  -> "swap_win": the original imposter wins
      * anything else (wrong player/tie)-> "escaped": current imposter wins
    Returns (outcome, [winner_sids]).
    """
    current  = room["imposter_sid"]
    original = room.get("original_imposter_sid") or current
    swapped  = original != current

    if top_sid is not None and top_sid == current:
        return "caught", [s for s in room["members"] if s != current]
    if swapped and top_sid is not None and top_sid == original:
        return "swap_win", [original]
    return "escaped", [current]


@socketio.on("imposter_power_swap")
def on_imposter_power_swap(data):
    """25 pts. A random innocent becomes the Imposter (title AND card move
    with it), and the caller becomes an innocent holding the real card."""
    sid = request.sid
    room = _imposter_power_check(sid, "swap")
    if not room:
        return
    others = [s for s in room["members"] if s != sid]
    if not others:
        _imposter_power_denied(sid, "Nobody to swap with.")
        return
    target = random.choice(others)

    _imposter_spend(room, sid, "swap")
    room["pending_choices"].pop(target, None)
    cards = room["player_cards"]
    cards[sid], cards[target] = cards[target], cards[sid]
    room["imposter_sid"] = target

    _imposter_log_power(room, sid, "swap", f"swapped roles with {players.get(target, '?')}")
    _imposter_send_role_update(room, sid, "Swapped! You're INNOCENT now - someone else holds the Imposter title.")
    _imposter_send_role_update(room, target, "You've been made the IMPOSTER! Your card changed.")


@socketio.on("imposter_power_request_choices")
def on_imposter_power_request_choices(data):
    """10 pts (charged when they PICK, not when they look). Offers two cards:
    the real one and a random decoy, shuffled so the Imposter can't tell
    which is which. Neither is the card they're already holding."""
    sid = request.sid
    room = _imposter_power_check(sid, "choose")
    if not room:
        return
    real    = room["secret_card"]
    current = room["player_cards"].get(sid)
    if current == real:
        _imposter_power_denied(sid, "Your secret already matches everyone else's.")
        return

    pending = room["pending_choices"].get(sid)
    if not pending:
        # Stored the first time so cancelling and re-opening can't be used
        # to re-roll the decoy (the card that shows up every time = the real one).
        if _get_category_cards is None:
            _imposter_power_denied(sid, "This server can't offer card choices right now.")
            return
        pool = [c["name"] for c in _get_category_cards(room["category"])
                if c["name"] not in (real, current)]
        if not pool:
            _imposter_power_denied(sid, "No other cards available to offer.")
            return
        pending = [real, random.choice(pool)]
        random.shuffle(pending)
        room["pending_choices"][sid] = pending

    socketio.emit("imposter_power_choices", {
        "cards": pending, "cost": IMPOSTER_POWER_COSTS["choose"],
    }, to=sid)


@socketio.on("imposter_power_pick")
def on_imposter_power_pick(data):
    sid = request.sid
    room = _imposter_power_check(sid, "choose")
    if not room:
        return
    pending = list(room["pending_choices"].get(sid) or [])
    card = str((data or {}).get("card", "")).strip()
    if card not in pending:
        _imposter_power_denied(sid, "Those choices are no longer available.")
        return

    _imposter_spend(room, sid, "choose")      # also clears the pending pair
    room["player_cards"][sid] = card
    note = "matches the real card" if card == room["secret_card"] else "decoy"
    _imposter_log_power(room, sid, "choose", f"picked {card} ({note})")
    _imposter_send_role_update(room, sid, f"Your secret is now {card}.")


@socketio.on("imposter_power_match")
def on_imposter_power_match(data):
    """50 pts. Guaranteed: the Imposter's card becomes the real one."""
    sid = request.sid
    room = _imposter_power_check(sid, "match")
    if not room:
        return
    real = room["secret_card"]
    if room["player_cards"].get(sid) == real:
        _imposter_power_denied(sid, "Your secret already matches everyone else's.")
        return

    _imposter_spend(room, sid, "match")
    room["player_cards"][sid] = real
    _imposter_log_power(room, sid, "match", f"card changed to the real card ({real})")
    _imposter_send_role_update(room, sid, f"Your secret is now {real}.")


@socketio.on("imposter_play_again")
def on_imposter_play_again(data):
    """Host resets the room back to its lobby state so the same group can
    play another round without everyone re-inviting each other."""
    sid = request.sid
    room_id = player_room.get(sid)
    room = imposter_rooms.get(room_id) if room_id else None
    if not room or room["host"] != sid:
        return
    room.update({
        "started": False, "secret_card": None, "imposter_sid": None,
        "imposter_card": None, "round": 0, "turn_order": [], "turn_idx": 0,
        "votes": {}, "transcript": [],
    })
    room.update(_imposter_blank_power_state())
    _imposter_room_broadcast(room_id, "imposter_room_state", _imposter_room_public_state(room_id))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)