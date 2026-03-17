FROM alfg/nginx-rtmp:latest

RUN apk add --no-cache ffmpeg curl

COPY nginx.conf /etc/nginx/nginx.conf
COPY scripts /opt/scripts
COPY transcode.sh /opt/transcode.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /opt/scripts/*.sh /opt/transcode.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]