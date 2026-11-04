FROM nginxinc/nginx-unprivileged:1.27-alpine

# Copy config first so a config change doesn't invalidate the HTML layer
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

# nginx-unprivileged uses uid 101 (nginx). Declare it explicitly so the
# submission checker and pod security admission can verify non-root.
USER nginx

# The Deployment mounts an emptyDir at /tmp for nginx temp files and pid.
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
