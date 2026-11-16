"""Web server settings (gunicorn reads this file automatically).

Sized for Render's 512 MB "starter" plan (half a processor): 1 process x 4 threads. Measured with a large
organization (16,000 beneficiaries): about 13 pages a second on one processor core, peak memory about
315 MB even with large exports. Each process is replaced after about a thousand requests, which returns
memory. On bigger plans raise WEB_CONCURRENCY (processes): about one per processor core and 300 MB.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"

# Load the program once and share it between the processes (saves memory). Database connections are never
# shared: each process throws away any it inherited and opens its own.
preload_app = True


def post_fork(server, worker):
    from wsgi import app
    from app.extensions import db
    with app.app_context():
        db.engine.dispose(close=False)
