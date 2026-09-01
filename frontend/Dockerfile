# Frontend — build tĩnh, rồi Caddy phục vụ nó và làm luôn reverse proxy.
#
# Hai vai trong một container là có chủ ý: mục tiêu vận hành ở DESIGN 11.3 là
# ≤ 5 container trên đường chính (`db`, `redis`, `backend`, `mezon_bot`,
# proxy) — một container nginx riêng cho file tĩnh sẽ là cái thứ sáu, và nó
# chỉ tồn tại để đứng cạnh proxy.
FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `/api` chứ không phải `http://localhost:8000/api`: Caddy phục vụ trang và
# proxy /api ở **cùng origin**, nên đường tương đối vừa bỏ được CORS vừa đúng
# dù truy cập bằng localhost, bằng IP LAN, hay sau này bằng tên miền. Giá trị
# này được nướng vào bundle lúc build — đổi nó là phải build lại.
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM caddy:2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

EXPOSE 5173

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:5173/ || exit 1
