# Optional dynamic host (live API mode). Static hosting of web/ needs no container.
FROM python:3.11-slim
WORKDIR /app
COPY whobrokeprod ./whobrokeprod
COPY web ./web
ENV PORT=8000
EXPOSE 8000
USER nobody
CMD ["sh", "-c", "python -m whobrokeprod.presentation.server --host 0.0.0.0 --port ${PORT}"]
