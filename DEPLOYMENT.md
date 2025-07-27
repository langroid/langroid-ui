# Deployment Guide

This guide covers various deployment options for the Langroid Chat UI.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Frontend Deployment](#frontend-deployment)
  - [Vercel](#vercel)
  - [Netlify](#netlify)
  - [GitHub Pages](#github-pages)
- [Backend Deployment](#backend-deployment)
  - [Railway](#railway)
  - [Render](#render)
  - [Heroku](#heroku)
  - [Docker](#docker)
- [Full Stack Deployment](#full-stack-deployment)

## Prerequisites

Before deploying, ensure you have:

1. Built the frontend: `cd frontend && npm run build`
2. Set up environment variables
3. Tested the application locally

## Environment Variables

### Frontend (.env.production)

```env
VITE_BACKEND_URL=https://your-backend-api.com
```

### Backend (.env)

```env
OPENAI_API_KEY=your-openai-api-key
HOST=0.0.0.0
PORT=8000
ALLOWED_ORIGINS=https://your-frontend-domain.com
```

## Frontend Deployment

### Vercel

1. Install Vercel CLI: `npm i -g vercel`
2. Build the frontend: `cd frontend && npm run build`
3. Deploy: `vercel --prod`
4. Set environment variable in Vercel dashboard

### Netlify

1. Build the frontend: `cd frontend && npm run build`
2. Drag and drop the `frontend/dist` folder to Netlify
3. Or use Netlify CLI:
   ```bash
   npm i -g netlify-cli
   netlify deploy --prod --dir=frontend/dist
   ```

### GitHub Pages

1. Install gh-pages: `npm install --save-dev gh-pages`
2. Add to package.json scripts:
   ```json
   "predeploy": "npm run build",
   "deploy": "gh-pages -d dist"
   ```
3. Deploy: `npm run deploy`

## Backend Deployment

### Railway

1. Create a `railway.json` in the backend directory:
   ```json
   {
     "build": {
       "builder": "NIXPACKS"
     },
     "deploy": {
       "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT"
     }
   }
   ```

2. Deploy:
   ```bash
   railway login
   railway up
   ```

### Render

1. Create a `render.yaml`:
   ```yaml
   services:
     - type: web
       name: langroid-chat-backend
       env: python
       buildCommand: "pip install -r requirements.txt"
       startCommand: "uvicorn main:app --host 0.0.0.0 --port $PORT"
   ```

2. Connect GitHub repo and deploy

### Heroku

1. Create `Procfile` in backend directory:
   ```
   web: uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

2. Create `runtime.txt`:
   ```
   python-3.11.0
   ```

3. Deploy:
   ```bash
   heroku create your-app-name
   heroku config:set OPENAI_API_KEY=your-key
   git push heroku main
   ```

### Docker

1. Create `Dockerfile` in backend directory:
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY . .

   EXPOSE 8000

   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

2. Build and run:
   ```bash
   docker build -t langroid-chat-backend .
   docker run -p 8000:8000 --env-file .env langroid-chat-backend
   ```

## Full Stack Deployment

### Using Docker Compose

Create `docker-compose.yml` in the root directory:

```yaml
version: '3.8'

services:
  frontend:
    build: ./frontend
    ports:
      - "80:80"
    environment:
      - VITE_BACKEND_URL=http://backend:8000
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - ./backend/.env
```

### Using a VPS (DigitalOcean, AWS EC2, etc.)

1. Set up a Linux server
2. Install Docker and Docker Compose
3. Clone your repository
4. Run: `docker-compose up -d`
5. Set up Nginx as reverse proxy:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Production Considerations

1. **SSL/TLS**: Always use HTTPS in production
2. **Environment Variables**: Never commit sensitive data
3. **Logging**: Set up proper logging and monitoring
4. **Scaling**: Consider using a load balancer for high traffic
5. **Database**: For persistent chat history, add a database
6. **Rate Limiting**: Implement rate limiting to prevent abuse
7. **CORS**: Configure CORS properly for your domains

## Monitoring

Consider adding:
- **Sentry** for error tracking
- **LogRocket** or **FullStory** for session replay
- **New Relic** or **DataDog** for performance monitoring
- **Prometheus** + **Grafana** for metrics