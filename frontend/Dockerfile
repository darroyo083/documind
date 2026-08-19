FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_PUBLIC_DEMO_MODE=true
ARG VITE_DEMO_VIDEO_SRC=
ARG VITE_DEMO_VIDEO_POSTER=
ENV VITE_PUBLIC_DEMO_MODE=$VITE_PUBLIC_DEMO_MODE \
    VITE_DEMO_VIDEO_SRC=$VITE_DEMO_VIDEO_SRC \
    VITE_DEMO_VIDEO_POSTER=$VITE_DEMO_VIDEO_POSTER

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
