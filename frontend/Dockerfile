# syntax=docker/dockerfile:1

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Staging/preview: VITE_BASE_PATH=/ledgerlink/ VITE_API_BASE=/ledgerlink
# Production root: VITE_BASE_PATH=/ VITE_API_BASE= (empty)
ARG VITE_BASE_PATH=/ledgerlink/
ARG VITE_API_BASE=/ledgerlink
ARG VITE_OPEN_REPLAY_PROJECT_KEY=
ENV VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_API_BASE=${VITE_API_BASE} \
    VITE_OPEN_REPLAY_PROJECT_KEY=${VITE_OPEN_REPLAY_PROJECT_KEY}

RUN npm run build

FROM nginx:1.27-alpine

# prefix = staging under /ledgerlink; root = production at /
ARG DEPLOY_BASE=prefix
ARG HEALTHCHECK_PATH=/ledgerlink/

COPY nginx.prefix.conf /tmp/nginx.prefix.conf
COPY nginx.root.conf /tmp/nginx.root.conf
COPY --from=build /app/dist /tmp/spa-dist

RUN if [ "$DEPLOY_BASE" = "root" ]; then \
      cp -a /tmp/spa-dist/. /usr/share/nginx/html/ && \
      cp /tmp/nginx.root.conf /etc/nginx/conf.d/default.conf; \
    elif [ "$DEPLOY_BASE" = "prefix" ]; then \
      mkdir -p /usr/share/nginx/html/ledgerlink && \
      cp -a /tmp/spa-dist/. /usr/share/nginx/html/ledgerlink/ && \
      cp /tmp/nginx.prefix.conf /etc/nginx/conf.d/default.conf; \
    else \
      echo "ERROR: DEPLOY_BASE must be 'root' or 'prefix', got: $DEPLOY_BASE" >&2; \
      exit 1; \
    fi && \
    rm -rf /tmp/spa-dist /tmp/nginx.prefix.conf /tmp/nginx.root.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1${HEALTHCHECK_PATH}" >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
