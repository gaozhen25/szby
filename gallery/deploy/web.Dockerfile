FROM nginx:latest
COPY deploy/web.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
