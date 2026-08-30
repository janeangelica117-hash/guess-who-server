import os
import random
import uuid
from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# { socket_id: username }
players = {}

# { socket_id: partner_socket_id }
matches = {}

# { socket_id: True } — tracks who is the host of their match
hosts = {}

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


def broadcast_players():
    """Send each client the full player list with availability status."""
    for sid in players:
        others = []
        for s, u in players.items():
            if s == sid:
                continue
            status = "busy" if (s in matches or s in player_room) else "available"
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
    print(f"[+] {username} joined (sid={request.sid})")
    broadcast_players()


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

    socketio.emit("matched", {"opponent": accepter_username, "is_host": True},  to=sender_sid)
    socketio.emit("matched", {"opponent": sender_username,   "is_host": False}, to=accepter_sid)

    print(f"[match] {sender_username} (host) <-> {accepter_username}")
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

    print(f"[leave_match] {players.get(leaver_sid, '?')} left the match")
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

    # Notify kicked player
    socketio.emit("kicked", {"by": kicker_username}, to=partner_sid)
    # Notify host that kick succeeded
    socketio.emit("kick_success", {"player": partner_username}, to=kicker_sid)

    print(f"[kick] {kicker_username} kicked {partner_username}")
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
    print(f"[start] {starter_username} started the game")
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
        socketio.emit("secret", {"name": data.get("name", "")}, to=partner_sid)


@socketio.on("question")
def on_question(data):
    """Relay a question from the asker to the answerer."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("question", {
            "text":   data.get("text", ""),
            "secret": data.get("secret", ""),   # opponent's secret, piggybacked
        }, to=partner_sid)


@socketio.on("answer")
def on_answer(data):
    """Relay YES/NO answer back to the asker."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("answer", {
            "yes":    bool(data.get("yes", False)),
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
    """Relay a game-over result to the partner."""
    partner_sid = matches.get(request.sid)
    if partner_sid:
        socketio.emit("game_over", {
            "result": data.get("result", ""),
            "reason": data.get("reason", ""),
            "secret": data.get("secret", ""),   # sender's secret dessert name
        }, to=partner_sid)


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
        socketio.emit("category_select", {
            "category": data.get("category", "desserts"),
        }, to=partner_sid)


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
    username = players.pop(request.sid, "unknown")
    partner_sid = matches.pop(request.sid, None)
    hosts.pop(request.sid, None)

    if partner_sid:
        matches.pop(partner_sid, None)
        hosts.pop(partner_sid,   None)
        socketio.emit("opponent_left", {}, to=partner_sid)

    _imposter_remove_player(request.sid)

    print(f"[-] {username} left (sid={request.sid})")
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
        "votes": {},
    }
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
        "turn_idx": 0, "votes": {},
    })

    for m_sid in members:
        socketio.emit("imposter_game_started", {
            "your_card":  imposter_card if m_sid == imposter_sid else real_card,
            "is_imposter": (m_sid == imposter_sid),
            "turn_order": [players.get(s, "?") for s in turn_order],
            "category":   room["category"],
        }, to=m_sid)

    print(f"[imposter] room {room_id} started: {len(members)} players, imposter is {players.get(imposter_sid)}")
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
    caught    = (len(top_sids) == 1 and top_sids[0] == room["imposter_sid"])

    room["round"] = 5
    _imposter_room_broadcast(room_id, "imposter_result", {
        "caught":    caught,
        "imposter":  players.get(room["imposter_sid"], "?"),
        "real_card": room["secret_card"],
        "votes":     {players.get(v, "?"): players.get(a, "?") for v, a in room["votes"].items()},
    })


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
        "votes": {},
    })
    _imposter_room_broadcast(room_id, "imposter_room_state", _imposter_room_public_state(room_id))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)