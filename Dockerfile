# Credit Memo GenAI — container image.
#
# By default this builds the lightweight offline/mock image (no Azure SDKs,
# no browser). To include the Azure stack + Playwright Chromium, build with:
#   docker build --build-arg INSTALL_AZURE=1 -t credit-memo .
FROM python:3.11-slim

ARG INSTALL_AZURE=0
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8001

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt requirements-azure.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    if [ "$INSTALL_AZURE" = "1" ]; then \
        pip install --no-cache-dir -r requirements-azure.txt && \
        python -m playwright install --with-deps chromium ; \
    fi

COPY . .

EXPOSE 8001

# HOST=0.0.0.0 so the server is reachable from outside the container.
CMD ["python", "run.py"]
