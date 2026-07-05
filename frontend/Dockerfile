FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

COPY . .

# Build args become Next.js server-side env vars at build time
ARG HCIP_API_URL=http://hcip-api:8000
ARG HCIP_API_KEY=""
ARG NEXT_PUBLIC_DEFAULT_KB_ID=kb-clinical-2024

ENV HCIP_API_URL=$HCIP_API_URL
ENV HCIP_API_KEY=$HCIP_API_KEY
ENV NEXT_PUBLIC_DEFAULT_KB_ID=$NEXT_PUBLIC_DEFAULT_KB_ID
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
