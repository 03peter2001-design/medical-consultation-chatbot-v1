# SMART 本機 proxy 設定

此目錄保存 `compose.smart.yml` 使用的 Nginx 設定：

- `fhir-proxy.conf`：將容器內 FHIR root request 代理至主機 HAPI Server
- `smart-launcher-gateway.conf`：依實際 localhost／127.0.0.1 port 正規化
  SMART Launcher CORS headers，並禁止快取 discovery／metadata

這些設定由 `./scripts/start-smart.sh` 與 `compose.smart.yml` 載入，通常不需單獨
啟動。完整流程、ports 與安全邊界請見
[../smart-app/README.md](../smart-app/README.md)。
