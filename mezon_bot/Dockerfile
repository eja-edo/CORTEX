# Cortex Mezon bot.
#
# Hai vai trong một tiến trình: một socket đi ra gateway Mezon, và một HTTP
# server đi vào ở cổng 8100 để backend gọi khi có gì cần gửi. Cổng đó **không
# publish ra host** — nó chỉ được gọi từ trong mạng compose, đúng như ghi chú
# ở `mezon_bot/.env.example`: khoá nội bộ cho phép hành động với tư cách bất
# kỳ user nào.
#
# bookworm-slim chứ không phải alpine: `@resvg/resvg-js` là native addon, và
# package-lock.json ghim bản glibc. Trên musl npm sẽ đi tìm một artefact khác.
FROM node:22-bookworm-slim

ENV NODE_ENV=production

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY . .

EXPOSE 8100

# `fetch` toàn cục có sẵn từ Node 18, nên không phải cài curl chỉ để hỏi một
# câu. `/health` nằm trước lớp auth trong server.js, có chủ ý.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://localhost:8100/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "src/index.js"]
