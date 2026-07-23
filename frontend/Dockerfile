# Build stage
ARG NODE_IMAGE=node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:mainline-alpine@sha256:18d67281256ded39ff65e010ae4f831be18f19356f83c60bc546492c7eb6dd23
FROM ${NODE_IMAGE} AS build

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the app
RUN npm run build

# Production stage
FROM ${NGINX_IMAGE}

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Keep the runtime identity explicit for scanners and derived images.  The
# nginx-unprivileged image defines UID 101 as its non-root nginx user.
USER 101

# Expose port
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
