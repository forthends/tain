FROM node:23-alpine AS css-builder
WORKDIR /app
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui/tailwind.config.js webui/src/input.css ./
RUN npx tailwindcss -i src/input.css -o static/tailwind.css --minify

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip install uvicorn
COPY . .
COPY --from=css-builder /app/static/tailwind.css webui/static/tailwind.css
ENV TAIN_API_KEY=""
ENV MINIMAX_API_KEY=""
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1
CMD ["python", "-m", "uvicorn", "webui.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
