# SMART 本機 proxy 設定

## 版本關係與更新紀錄

此目錄不是可獨立執行的服務；其中的 Nginx 設定由 `compose.smart.yml` 與
`./scripts/start-smart.sh` 載入，因此隨 **SMART sandbox v1.0.0** 維護，版本與
`smart-app` 相同。這是截至 2026-08-05 依 `devlog/` 回溯建立的文件基線，
repository 目前沒有對應的 Git tag。

### v1.0.0（隨 SMART sandbox，截至 2026-08-05）

- **2026-07-29**：建立 FHIR root proxy 與 SMART Launcher CORS gateway；依實際
  localhost／127.0.0.1 port 正規化 CORS，並為 discovery response 加入
  `no-store` 與 Nginx 安全 headers。
- **2026-08-04**：配合版本化 API，健康檢查路徑同步為 `/api/v1/health`。
- **2026-08-05**：FHIR proxy upstream 改為 Compose service `hapi:8080`，移除
  host gateway 依賴。

此目錄保存 `compose.smart.yml` 使用的 Nginx 設定：

- `fhir-proxy.conf`：將容器內 FHIR root request 代理至 Compose 內的 HAPI Server
- `smart-launcher-gateway.conf`：依實際 localhost／127.0.0.1 port 正規化
  SMART Launcher CORS headers，並禁止快取 discovery／metadata

這些設定由 `./scripts/start-smart.sh` 與 `compose.smart.yml` 載入，通常不需單獨
啟動。完整流程、ports 與安全邊界請見
[../smart-app/README.md](../smart-app/README.md)。
