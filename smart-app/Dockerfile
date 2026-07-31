FROM node:20-alpine AS frontend

WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
ARG VITE_BACKEND_BASE_URL=/api
ENV VITE_BACKEND_BASE_URL=${VITE_BACKEND_BASE_URL}
ENV VITE_ENABLE_DIRECT_FHIR=false
RUN npm run build

FROM node:20-alpine AS fhirclient

WORKDIR /dependencies
RUN npm install --ignore-scripts --no-audit --no-fund fhirclient@2.6.3

FROM nginx:1.27-alpine

COPY smart-app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend /workspace/frontend/dist/ /usr/share/nginx/html/
COPY smart-app/launch.html /usr/share/nginx/html/launch.html
COPY smart-app/launch-patient.html /usr/share/nginx/html/launch-patient.html
COPY smart-app/start.html /usr/share/nginx/html/start.html
COPY --from=fhirclient \
    /dependencies/node_modules/fhirclient/build/fhir-client.js \
    /usr/share/nginx/html/vendor/fhir-client.js

EXPOSE 80
