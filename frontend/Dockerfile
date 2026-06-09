# MyTrend 프론트엔드 이미지 — nginx 가 정적 SPA 서빙 + /api/ 를 백엔드로 프록시.
#   build context: ./frontend
FROM nginx:1.27-alpine

# 정적 자산
COPY index.html /usr/share/nginx/html/index.html

# nginx 공식 이미지의 엔트리포인트가 templates/*.template 를 envsubst 처리해
# /etc/nginx/conf.d/ 로 렌더링한다. ${NGINX_PORT}/${BACKEND_HOST}/${BACKEND_PORT} 치환.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# 기본값(dev). compose 가 prod 에서 오버라이드.
ENV NGINX_PORT=80 \
    BACKEND_HOST=backend \
    BACKEND_PORT=8000

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null "http://localhost:${NGINX_PORT}/" || exit 1
