FROM alfg/nginx-rtmp:latest

RUN apk add --no-cache ffmpeg curl

COPY nginx.conf /etc/nginx/nginx.conf
COPY scripts /opt/scripts
RUN chmod +x /opt/scripts/*.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]