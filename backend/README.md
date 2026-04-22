# DroneDream Backend

FastAPI app for the DroneDream MVP. Phase 0 ships only a health endpoint and
the standard response envelope helper.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/uvicorn app.main:app --reload --app-dir . --host 127.0.0.1 --port 8000
```

Run the test suite:

```bash
.venv/bin/pytest
```
