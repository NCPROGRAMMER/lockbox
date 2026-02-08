from flask import Flask, jsonify
import redis
import os
import socket
from datetime import datetime, timezone

app = Flask(__name__)

def _candidate_redis_hosts():
    configured = os.getenv("REDIS_HOST")
    if configured:
        return [configured]

    # Prefer service-name networking when available, but keep reliable fallbacks.
    return ["redis-db", "127.0.0.1", "host.docker.internal"]


def get_redis_connection():
    last_error = None
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    for host in _candidate_redis_hosts():
        client = redis.Redis(host=host, port=redis_port, db=0, socket_timeout=2)
        try:
            client.ping()
            return client, host
        except Exception as err:
            last_error = err

    raise ConnectionError(f"Unable to connect to Redis: {last_error}")

@app.route('/')
def hello():
    try:
        r, redis_host = get_redis_connection()
        count = r.incr('hits')
        server_id = socket.gethostname()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"""
        <div style="font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h1>🔒 LockBox Create Demo</h1>
            <p>I have been seen <b>{count}</b> times.</p>
            <p><small>Redis host: {redis_host}</small></p>
            <p><small>Time: {now}</small></p>
            <p><small>Served by Container ID: {server_id}</small></p>
        </div>
        """
    except Exception as e:
        return f"<h3>DB Connection Error:</h3> <p>{e}</p>", 503


@app.route('/healthz')
def healthz():
    try:
        _, redis_host = get_redis_connection()
        return jsonify(status="ok", redis_host=redis_host), 200
    except Exception as e:
        return jsonify(status="error", error=str(e)), 503

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
