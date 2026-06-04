import os
from flask import Flask, request
from flask_socketio import SocketIO, emit

app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# { socket_id: username }
players = {}


@socketio.on("join")
def on_join(data):
    username = str(data.get("username", "")).strip()
    if not username:
        return
    players[request.sid] = username
    print(f"[+] {username} joined (sid={request.sid})")
    # Send each client the list of OTHER players only
    for sid in players:
        others = [u for s, u in players.items() if s != sid]
        socketio.emit("update_players", others, to=sid)


@socketio.on("disconnect")
def on_disconnect():
    username = players.pop(request.sid, "unknown")
    print(f"[-] {username} left (sid={request.sid})")
    for sid in players:
        others = [u for s, u in players.items() if s != sid]
        socketio.emit("update_players", others, to=sid)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)