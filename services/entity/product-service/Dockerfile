# Build context: thư mục gốc dự án (để copy được thư viện dùng chung common/)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8002
WORKDIR /app
COPY services/entity/product-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY services/entity/product-service/ .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 60 "app:create_app()"
