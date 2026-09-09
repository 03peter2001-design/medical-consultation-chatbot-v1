# SMART 本機 proxy 設定

## 版本關係與更新紀錄

此目錄不是可獨立執行的服務；其中的 Nginx 設定由 `compose.smart.yml` 與
`./scripts/start-smart.sh` 載入，因此隨 **SMART sandbox v1.1.2** 維護，版本與
`smart-app` 相同。這是截至 2026-08-28 依 `devlog/` 維護的文件基線，
repository 目前沒有對應的 Git tag。

### v1.1.2 (2026-08-28)

- SMART FHIR request 使用 `Cache-Control: no-cache` 防止不同 OAuth launch state 共用
  Patient response；gateway 的 CORS allow-list 現在明確允許 `Cache-Control` 與瀏覽器
  可能附帶的 `Pragma`，避免 preflight 成功回 204 後仍被瀏覽器拒絕。
- FHIR root proxy 對 HAPI pagination 的精確 `/fhir` base path 提供 compatibility alias，
  避免 SMART public base 將 next link 解析成重複的 `/v/r4/fhir/fhir`。
- Compose 傳給 Backend 的 `FHIR_PUBLIC_ISSUER` 現在跟隨 `SMART_LAUNCHER_PORT`，與瀏覽器
  callback issuer 完全一致，同時仍維持單一 issuer 的 fail-closed 比對。
- Origin allow-list 仍限制在帶 port 的 loopback HTTP origin，不允許 wildcard。靜態
  regression test 位於 `tests/test_gateway_config.py`。

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
