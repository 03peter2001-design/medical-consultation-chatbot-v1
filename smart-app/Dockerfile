FROM node:20-alpine AS fhirclient

WORKDIR /dependencies
RUN npm install --ignore-scripts --no-audit --no-fund fhirclient@2.6.3

FROM python:3.12-alpine

WORKDIR /app
COPY . /app
COPY --from=fhirclient \
    /dependencies/node_modules/fhirclient/build/fhir-client.js \
    /app/vendor/fhir-client.js

EXPOSE 80
CMD ["python", "-m", "http.server", "80", "--bind", "0.0.0.0"]
