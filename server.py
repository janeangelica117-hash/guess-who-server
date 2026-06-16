import os
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


def broadcast_players():
    """Send each client the full player list with availability status."""
    for sid in players:
        others = []
        for s, u in players.items():
            if s == sid:
                continue
            status = "busy" if s in matches else "available"
            others.append({"username": u, "status": status})
        socketio.emit("update_players", others, to=sid)


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


@socketio.on("chat_emoji")
def on_chat_emoji(data):
    """Relay an emoji reaction to the partner (shown on both screens)."""
    partner_sid = matches.get(request.sid)
    emoji = str(data.get("emoji", "")).strip()
    if partner_sid and emoji:
        socketio.emit("chat_emoji", {"emoji": emoji}, to=partner_sid)


@socketio.on("disconnect")
def on_disconnect():
    username = players.pop(request.sid, "unknown")
    partner_sid = matches.pop(request.sid, None)
    hosts.pop(request.sid, None)

    if partner_sid:
        matches.pop(partner_sid, None)
        hosts.pop(partner_sid,   None)
        socketio.emit("opponent_left", {}, to=partner_sid)

    print(f"[-] {username} left (sid={request.sid})")
    broadcast_players()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)