from flask import Flask
import redis
import os
import socket

app = Flask(__name__)

# Connect to the Redis container by its service name defined in YAML
# We use a retry loop because the DB might take a second to start
def get_redis_connection():
    return redis.Redis(host='redis-db', port=6379, db=0, socket_timeout=5)

@app.route('/')
def hello():
    try:
        r = get_redis_connection()
        count = r.incr('hits')
        server_id = socket.gethostname()
        return f"""
        <div style="font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h1>🔒 LockBox Create Demo</h1>
            <p>I have been seen <b>{count}</b> times.</p>
            <p><small>Served by Container ID: {server_id}</small></p>
        </div>
        """
    except Exception as e:
        return f"<h3>DB Connection Error:</h3> <p>{e}</p>"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)