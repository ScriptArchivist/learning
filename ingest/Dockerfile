# Config + scripts
COPY nginx.conf /etc/nginx/nginx.conf
COPY scripts/ /opt/scripts/
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /opt/scripts/*.sh /entrypoint.sh \
 && nginx -t

EXPOSE 1935

CMD ["/entrypoint.sh"]