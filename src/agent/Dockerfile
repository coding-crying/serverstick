FROM python:3.13-slim AS backend

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Build the Svelte dashboard
FROM node:22-slim AS dashboard
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ .
RUN npm run build

# Final image
FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker-compose-v2 \
    && rm -rf /var/lib/apt/lists/*

# Copy backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Copy built dashboard
COPY --from=dashboard /app/dashboard/build /app/dashboard/build

# Create data directories
RUN mkdir -p /etc/serverstick/secrets \
    /var/lib/serverstick/data \
    /etc/serverstick/services

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]