# 🔒 LockBox Create Demo (Web + Redis)

This demo shows how to run a simple **Flask web application backed by Redis** using **LockBox Create** — a Docker-style compose workflow that runs on LockBox’s isolated Alpine-based containers.

**No Docker daemon is required.**

---

## ✨ What This Demo Demonstrates

- Building images from local `app.lbox` files  
- Running multiple services (web + redis) with `lockbox-create.yml`  
- Port forwarding from containers to the host  
- Absolute-path container startup (**required for LockBox v4.7+**)

---

## 📦 Requirements

### Windows
- Python **3.10+**
- WSL installed and working (`wsl --status`)
- LockBox installed and available as `lbox` in your PATH

### Linux
- Python **3.10+**
- Root access (LockBox uses `chroot` and mount namespaces)

---

## 📁 Project Structure

```text
LockBox_Demo/
├── app.py
├── requirements.txt
├── app.lbox
├── lockbox-create.yml
└── db/
    └── app.lbox
```

### Key Files

**`app.lbox`**  
Builds the Flask web image and starts the app using absolute paths:

```
/app/venv/bin/python /app/app.py
```

**`db/app.lbox`**  
Builds a Redis image and runs Redis bound to `0.0.0.0`.

**`lockbox-create.yml`**  
Defines the `web` and `redis-db` services and port mappings.

---

## 🧠 Why Absolute Paths Matter

LockBox v4.7 runs container commands from the **LockBox install directory**, not from the service build context.

Because of this, commands like:

```bash
python app.py
```

will fail, since `app.py` is not in the current working directory.

This demo fixes the issue by:
- Copying application files to `/app` inside the container
- Starting the application using **absolute paths**

This behavior is intentional and required for reliable startup.

---

## 🚀 Running the Demo

From the directory containing `lockbox-create.yml`, run:

```bash
lbox create up
```

Then open your browser:

```
http://localhost:8080
```

You should see a page showing a hit counter backed by Redis.

---

## 🛑 Stopping the Demo

To stop and remove all services:

```bash
lbox create down
```

This will stop and remove:
- The web container
- The Redis container
- The auto-update monitor (if enabled)

---

## 🔌 Ports

| Service | Host Port | Container Port |
|-------|-----------|----------------|
| Web   | 8080      | 5000           |
| Redis | 6379      | 6379           |

You can change these values in `lockbox-create.yml`.

---

## 🌐 Redis Networking Note

LockBox does **not** provide Docker-style internal DNS between services.

For this reason, Redis is exposed on the host, and the web app connects using:
- `127.0.0.1`
- The WSL gateway IP (on Windows)
- An optional `REDIS_HOST` environment variable

This keeps the demo predictable and portable across systems.

---

## 🧯 Troubleshooting

### Web container exits immediately
- Check logs:
  ```bash
  lbox logs <container-id>
  ```
- Verify `BOX_START` uses absolute paths

### Port already in use
- Change ports in `lockbox-create.yml`
- Or stop the conflicting service

---

## 📄 License

Demo code is provided for testing and experimentation with **LockBox**.
