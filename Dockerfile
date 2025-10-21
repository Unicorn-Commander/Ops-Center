# Build stage for React app
FROM node:20-alpine as frontend-build

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm install

# Copy source code
COPY src ./src
COPY public ./public
COPY index.html ./
COPY vite.config.js ./
COPY tailwind.config.js ./
COPY postcss.config.js ./

# Build the React app
RUN npm run build

# Python backend stage
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    pciutils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/*.py ./
COPY backend/models ./models

# Copy built React app from frontend stage
COPY --from=frontend-build /app/dist ./dist

# Copy public files (including login.html)
COPY public ./public

# Expose port
EXPOSE 8084

# Run the server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8084"]