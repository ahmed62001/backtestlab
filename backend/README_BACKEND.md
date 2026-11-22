# Backend quickstart (5 commands)

```bash
cd backend
cp .env.example .env  # set LOCAL_JWT_SECRET (32+ chars), CORS_ORIGINS
pip install -r requirements-dev.txt   # core + providers + test/lint tools
python -m uvicorn app.main:app --port 8000  # http://localhost:8000/health
python -m pytest tests/ -q
ruff check . && ruff format --check . && mypy   # lint, format, types
```
