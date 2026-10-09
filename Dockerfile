# Optional dynamic host (live API mode). Static hosting of web/ needs no container.
# Runtime is stdlib-only: no pip install step, no credentials.
FROM python:3.11-slim
WORKDIR /app
COPY whobrokeprod ./whobrokeprod
COPY web ./web
COPY results ./results
COPY HYPOTHESES.md ./
ENV WBP_HOST=0.0.0.0 \
    PORT=8000 \
    WBP_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1
EXPOSE 8000
USER nobody
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"WBP_PORT\") or os.environ.get(\"PORT\") or 8000}/healthz', timeout=2)"
CMD ["python", "-m", "whobrokeprod.presentation.server"]
