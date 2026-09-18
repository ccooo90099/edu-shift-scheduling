# 内网部署用。单阶段就够 —— 没有前端构建步骤（HTMX 从 CDN 取，
# 或者按下面的说明改成本地文件），Python 也不需要编译。
FROM python:3.11-slim

# ortools 需要这些运行时库；--no-install-recommends 少装几十兆
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖再拷代码 —— 改代码不会让这一层缓存失效
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tools/ ./tools/
COPY console.py pytest.ini ./
COPY config/rules.example.yaml ./config/

# 数据与真实配置从卷挂进来，不进镜像
VOLUME ["/app/data", "/app/config"]

ENV PYTHONPATH=/app/src:/app \
    PYTHONUNBUFFERED=1 \
    SCHEDULING_DATA=/app/data

# 不用 root 跑
RUN useradd -r -u 1000 -m app && mkdir -p /app/data && chown -R app /app/data
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# 内网并发个位数，单 worker 足够。求解本身在应用内的线程池里跑，
# 多开 worker 反而会让任务状态分散在各进程的内存里。
CMD ["uvicorn", "scheduling.interfaces.web.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
