FROM python:3.11-slim
WORKDIR /app
COPY backend /app/backend
RUN pip install --no-cache-dir -e 'backend[postgres,storage]'
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
