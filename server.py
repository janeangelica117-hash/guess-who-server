import os
from flask import Flask, request
from flask_socketio import SocketIO, emit

app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# { socket_id: username }
players = {}

# { socket_id: partner_socket_id } — tracks who is matched with who
matches = {}


def broadcast_available_players():
    """Send each unmatched client the list of other available (unmatched) players."""
    for sid in players:
        if sid in matches:
            continue  # already matched, don't update their list
        others = [
            u for s, u in players.items()
            if s != sid and s not in matches
        ]
        socketio.emit("update_players", others, to=sid)


@socketio.on("join")
def on_join(data):
    username = str(data.get("username", "")).strip()
    if not username:
        return
    players[request.sid] = username
    print(f"[+] {username} joined (sid={request.sid})")
    broadcast_available_players()


@socketio.on("invite")
def on_invite(data):
    """Player A invites Player B by username."""
    target_username = str(data.get("target", "")).strip()
    sender_username = players.get(request.sid, "")

    # Find target's sid
    target_sid = next(
        (s for s, u in players.items() if u == target_username and s not in matches),
        None
    )

    if not target_sid:
        emit("invite_response", {"accepted": False, "reason": "Player not available."})
        return

    # Send invite to target
    socketio.emit("incoming_invite", {"from": sender_username}, to=target_sid)
    # Temporarily store pending invite
    socketio.emit("invite_pending", {"to": target_username}, to=request.sid)


@socketio.on("invite_accept")
def on_invite_accept(data):
    """Target accepts the invite."""
    sender_username = str(data.get("from", "")).strip()
    accepter_sid    = request.sid
    accepter_username = players.get(accepter_sid, "")

    sender_sid = next(
        (s for s, u in players.items() if u == sender_username),
        None
    )

    if not sender_sid:
        return

    # Match both players
    matches[sender_sid]   = accepter_sid
    matches[accepter_sid] = sender_sid

    # Notify both they are matched
    socketio.emit("matched", {"opponent": accepter_username}, to=sender_sid)
    socketio.emit("matched", {"opponent": sender_username},   to=accepter_sid)

    print(f"[match] {sender_username} <-> {accepter_username}")
    broadcast_available_players()


@socketio.on("invite_decline")
def on_invite_decline(data):
    """Target declines the invite."""
    sender_username = str(data.get("from", "")).strip()
    decliner_username = players.get(request.sid, "")

    sender_sid = next(
        (s for s, u in players.items() if u == sender_username),
        None
    )
    if sender_sid:
        socketio.emit("invite_declined", {"by": decliner_username}, to=sender_sid)


@socketio.on("disconnect")
def on_disconnect():
    username   = players.pop(request.sid, "unknown")
    partner_sid = matches.pop(request.sid, None)

    if partner_sid:
        matches.pop(partner_sid, None)
        socketio.emit("opponent_left", {}, to=partner_sid)

    print(f"[-] {username} left (sid={request.sid})")
    broadcast_available_players()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)