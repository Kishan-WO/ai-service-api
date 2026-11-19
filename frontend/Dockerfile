# Stage 1: build the static site
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# `npm install` (not `npm ci`): a lock file made on Windows lacks Linux-only optional packages,
# and `npm ci` refuses a lock file that is not complete for the platform.
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: serve it with nginx, and forward /api to the API container
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
