FROM alfg/nginx-rtmp:latest

RUN printf '%s\n%s\n' \
    'http://mirror.yandex.ru/mirrors/alpine/v3.16/main' \
    'http://mirror.yandex.ru/mirrors/alpine/v3.16/community' \
    > /etc/apk/repositories \
    && apk add --no-cache ffmpeg curl

COPY nginx.conf /etc/nginx/nginx.conf
COPY scripts /opt/scripts
COPY transcode.sh /opt/transcode.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /opt/scripts/*.sh /opt/transcode.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]