from __future__ import annotations

import argparse
import threading
import time
import uuid

from flask import Flask, g, jsonify, redirect, request, send_from_directory

from neo.config import load_config, project_root, set_debug_mode, static_dir
from neo.game import database as game_db
from neo.game import engine as game_engine
from neo.game import routes as game_routes
from neo.game import sse as game_sse
from neo.lobby import routes as lobby_routes
from neo.lobby import service as lobby_service
from neo.lobby import sse as lobby_sse

load_config()
game_db.init_database()

app = Flask(__name__, static_folder=str(static_dir()), static_url_path="")
# Leave API capacity free in the 32-thread, single-worker deployment.
_stream_slots = threading.BoundedSemaphore(24)


@app.before_request
def request_context():
    g.request_id = uuid.uuid4().hex[:12]
    g.request_started = time.monotonic()
    if request.path.startswith("/events/"):
        if not _stream_slots.acquire(blocking=False):
            return jsonify({"error": "Stream capacity reached; polling remains available"}), 503
        g.stream_slot = True


@app.after_request
def response_context(response):
    response.headers["X-Request-ID"] = g.request_id
    response.headers["Server-Timing"] = f"app;dur={(time.monotonic() - g.request_started) * 1000:.1f}"
    if getattr(g, "stream_slot", False):
        response.call_on_close(_stream_slots.release)
    return response


def _lobby_tick():
    while True:
        time.sleep(1)
        try:
            lobby_service.tick_all_rooms()
            game_engine.tick_all_rooms()
        except Exception:
            app.logger.exception("Room tick failed")


_tick_lock = threading.Lock()
_tick_started = False


def start_background_tasks():
    global _tick_started
    with _tick_lock:
        if not _tick_started:
            threading.Thread(target=_lobby_tick, daemon=True).start()
            _tick_started = True


def create_app():
    start_background_tasks()
    return app


game_engine.set_broadcast(game_sse.broadcast)
lobby_sse.set_broadcast_hook()

app.register_blueprint(game_routes.bp)
app.register_blueprint(lobby_routes.bp)


@app.route("/")
def root():
    return redirect("/lobby")


@app.route("/assets/<path:filename>")
def dist_assets(filename):
    return send_from_directory(static_dir() / "dist" / "assets", filename)


@app.route("/lobby")
def lobby_page():
    return send_from_directory(static_dir() / "dist", "lobby.html")


@app.route("/index.html")
def game_page():
    return send_from_directory(static_dir() / "dist", "index.html")


def parse_args():
    parser = argparse.ArgumentParser(description="Gensokyo Geo-Guesser Neo")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.debug:
        set_debug_mode(True)
    start_background_tasks()
    print(f"Starting Neo server on port {args.host}:{args.port} (debug={args.debug})")
    app.run(debug=args.debug, port=args.port, threaded=True, host=args.host)
