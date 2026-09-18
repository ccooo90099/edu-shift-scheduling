# 内网部署用。单阶段就够 —— 没有前端构建链（htmx 是一个文件，构建时下），
# Python 也不需要编译。
FROM python:3.11-slim

# ortools 需要这些运行时库；--no-install-recommends 少装几十兆
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖再拷代码 —— 改代码不会让这一层缓存失效
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# htmx 不在仓库里（开发沙箱访问不了外网，下不了）。构建时下一份 ——
# Render / HF / 本地 docker build 都能联网，这一步正常不会失败。
# 版本写死，不用 latest：CDN 上的 latest 变了会让页面行为跟着变。
#
# ⚠️ 没做哈希校验。我没法在开发环境下载这个文件、也就算不出可信的哈希，
#    与其写一个没验证过的数字，不如说清楚这里没校验。
#    真要收紧：自己下一份、算出 sha256 填到下面的 EXPECTED 里。
ARG HTMX_VERSION=1.9.12
RUN set -eu; \
    dest=src/scheduling/interfaces/web/static/htmx.min.js; \
    if [ ! -f "$dest" ]; then \
        (command -v curl >/dev/null && curl -fsSL -o "$dest" \
            "https://cdnjs.cloudflare.com/ajax/libs/htmx/${HTMX_VERSION}/htmx.min.js") \
        || (command -v wget >/dev/null && wget -qO "$dest" \
            "https://cdnjs.cloudflare.com/ajax/libs/htmx/${HTMX_VERSION}/htmx.min.js") \
        || echo "⚠ htmx 没下下来，页面会降级为整页刷新（功能不受影响）"; \
    fi
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

# 各家 PaaS 给的端口不一样：HF Spaces 要 7860，Render/Railway 给 $PORT。
# 默认 8000 给内网用。
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4)"

# 内网并发个位数，单 worker 足够。求解本身在应用内的线程池里跑，
# 多开 worker 反而会让任务状态分散在各进程的内存里。
# 用 shell 形式才能展开 $PORT
CMD uvicorn scheduling.interfaces.web.app:create_app --factory \
    --host 0.0.0.0 --port ${PORT:-8000}
