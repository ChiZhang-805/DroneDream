# DroneDream Worker

Background worker for the DroneDream MVP. In later phases it will poll a
DB-backed queue for `Trial` rows and execute the mock simulator. Phase 0 ships
only a runnable entrypoint that logs startup and shutdown — it does **not**
execute any trials yet.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m app.main
# or, after install:
.venv/bin/drone-dream-worker
```

Press `Ctrl+C` to stop; the worker logs a clean shutdown message.
