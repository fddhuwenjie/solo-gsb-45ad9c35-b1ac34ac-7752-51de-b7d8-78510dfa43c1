FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/guide.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录由 compose 挂载卷持久化; 启动时自动建库建表
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 5000

# init_db() 在入口中执行一次; 多 worker 时建表语句均为 IF NOT EXISTS, 安全
CMD ["sh", "-c", "python -c \"from app import init_db; init_db()\" && exec gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --access-logfile - --error-logfile - app:app"]
