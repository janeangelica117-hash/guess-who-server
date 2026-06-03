"""
server.py
─────────
Deploy this file on Railway (or any host).
Both players connect to the same hosted URL — no IP sharing needed.

Deploy steps:
  1. Push this project to GitHub.
  2. Go to railway.app → New Project → Deploy from GitHub repo.
  3. Railway auto-detects the Procfile and runs this file.
  4. Click "Generate Domain" and paste the URL into connection.py → SERVER_URL.
"""

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
    print(f"[+] {username} joined  (sid={request.sid})")
    # Tell everyone the updated player list
    emit("update_players", list(players.values()), broadcast=True)


@socketio.on("disconnect")
def on_disconnect():
    username = players.pop(request.sid, "unknown")
    print(f"[-] {username} left  (sid={request.sid})")
    emit("update_players", list(players.values()), broadcast=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)