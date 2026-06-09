# syntax=docker/dockerfile:1

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_BASE_PATH=/ledgerlink/
ARG VITE_API_BASE=/ledgerlink/api
ENV VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/ledgerlink

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ledgerlink/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
