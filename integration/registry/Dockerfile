# Build context: thư mục gốc dự án
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8500
WORKDIR /app
COPY integration/registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY integration/registry/ .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8500
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8500/health', timeout=2)"
# 1 worker: danh bạ lưu trong bộ nhớ của tiến trình
CMD gunicorn --bind 0.0.0.0:8500 --workers 1 --threads 8 --timeout 60 "app:create_app()"
