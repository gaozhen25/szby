
FROM harbor.bytech.tech/library/node:22-alpine-bytech AS builder

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG BUILD_ENV=prod

RUN pnpm run "build:web:${BUILD_ENV}"


############################
# 2. Nginx 托管
############################
FROM harbor.bytech.tech/library/nginx:1.28-alpine-bytech

RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]