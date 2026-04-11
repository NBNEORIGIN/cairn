# Cairn web UI — Next.js 14 production image.
#
# Two-stage build:
#   1. builder  — install deps, run `next build` with output: 'standalone'
#   2. runner   — node:20-alpine with just the trimmed standalone server
#                 bundle, .next/static, and public/ (manifest, icons, sw.js)
#
# The deployed container runs on port 3000 inside the Docker network and
# is exposed to the host at 127.0.0.1:3020 via the cairn deploy compose
# file. No external ports — nginx fronts it at cairn.nbnesigns.co.uk.

FROM node:20-alpine AS builder
WORKDIR /app

# Install deps first so they're cached independently of source edits.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy the rest and build.
COPY . .

# Cache-bust the build layer when the caller passes a fresh commit hash
# (same pattern as deploy/Dockerfile.api). Default 'dev' caches normally.
ARG GIT_COMMIT=dev
RUN echo "cairn-web build git_commit=${GIT_COMMIT}" > /app/.build_commit

RUN npm run build

# ── Runner stage ──────────────────────────────────────────────────────

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Non-root user for basic hardening. node:20-alpine already has the
# `node` user (uid 1000).
RUN chown -R node:node /app
USER node

# The standalone output includes a self-contained server.js plus a
# pruned node_modules tree. Static assets are NOT in standalone so they
# must be copied separately.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.build_commit ./.build_commit

EXPOSE 3000
CMD ["node", "server.js"]
