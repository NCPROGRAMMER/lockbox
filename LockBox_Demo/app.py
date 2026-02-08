from datetime import datetime, timezone
import os
import socket

from flask import Flask, jsonify
import redis

app = Flask(__name__)

_REDIS_CLIENTS = {}
_LAST_GOOD_HOST = None


def _candidate_redis_hosts():
    configured = os.getenv("REDIS_HOST")
    if configured:
        return [configured]

    # Prefer service-name networking when available, but keep reliable fallbacks.
    return ["redis-db", "127.0.0.1", "host.docker.internal"]


def _redis_port():
    return int(os.getenv("REDIS_PORT", "6379"))


def _get_or_create_client(host, port):
    key = (host, port)
    if key not in _REDIS_CLIENTS:
        _REDIS_CLIENTS[key] = redis.Redis(host=host, port=port, db=0, socket_timeout=2)
    return _REDIS_CLIENTS[key]


def _clear_cached_host():
    global _LAST_GOOD_HOST
    _LAST_GOOD_HOST = None


def get_redis_connection(force_probe=False):
    global _LAST_GOOD_HOST

    port = _redis_port()
    hosts = _candidate_redis_hosts()

    if _LAST_GOOD_HOST and _LAST_GOOD_HOST in hosts and not force_probe:
        return _get_or_create_client(_LAST_GOOD_HOST, port), _LAST_GOOD_HOST

    last_error = None

    if _LAST_GOOD_HOST and _LAST_GOOD_HOST in hosts:
        hosts = [_LAST_GOOD_HOST] + [host for host in hosts if host != _LAST_GOOD_HOST]

    for host in hosts:
        client = _get_or_create_client(host, port)
        try:
            client.ping()
            _LAST_GOOD_HOST = host
            return client, host
        except Exception as err:
            last_error = err

    raise ConnectionError(f"Unable to connect to Redis: {last_error}")


@app.route('/')
def hello():
    try:
        r, redis_host = get_redis_connection()
        count = r.incr('hits')
    except Exception:
        # Retry once with host probing in case cached host/client became stale.
        _clear_cached_host()
        try:
            r, redis_host = get_redis_connection(force_probe=True)
            count = r.incr('hits')
        except Exception as e:
            return f"<h3>DB Connection Error:</h3> <p>{e}</p>", 503

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


@app.route('/healthz')
def healthz():
    try:
        _, redis_host = get_redis_connection(force_probe=True)
        return jsonify(status="ok", redis_host=redis_host), 200
    except Exception as e:
        return jsonify(status="error", error=str(e)), 503


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
