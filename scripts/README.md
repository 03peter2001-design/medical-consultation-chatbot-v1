# 專案建制與啟動腳本

本目錄提供 repository 層級的環境準備與 SMART stack 啟動工具。

## 系統需求

| 工具 | 需求 | 安裝說明 |
| --- | --- | --- |
| Git、Bash | 可執行 `.sh` | [Git](https://git-scm.com/downloads) |
| Python | 3.12+，包含 `venv` | [Python](https://www.python.org/downloads/) |
| Node.js、npm | Node.js 18+ | [Node.js](https://nodejs.org/en/download) |
| Docker | Docker Engine 或 Docker Desktop | [Docker Engine](https://docs.docker.com/engine/install/) |
| Docker Compose | v2 plugin，使用 `docker compose` | [Compose](https://docs.docker.com/compose/install/) |

Ubuntu／Debian 可先安裝基本工具：

```bash
sudo apt update
sudo apt install -y git bash python3-venv
```

Python 3.12 與 Node.js 是否由系統 repository 提供取決於發行版；缺少時請使用
各自官方安裝方式。執行前可確認：

```bash
git --version
python3 --version
node --version
npm --version
docker --version
docker compose version
docker info
```

Windows 建議使用 WSL2 並啟用 Docker Desktop WSL integration；macOS 可使用
Docker Desktop。腳本不會用 `sudo` 修改作業系統。

## `bootstrap.sh`

從 repository 根目錄執行：

```bash
./scripts/bootstrap.sh
```

腳本會：

1. 尋找 Python 3.12+，建立 `backend/venv`
2. 安裝或更新 Python dependencies
3. 安裝 npm dependencies 並建置 Vue frontend
4. 在未略過 FHIR 時啟動 HAPI／PostgreSQL 並安裝 TW Core
5. 使用來源雜湊、輸出、container 狀態與 HAPI lock marker 跳過未變更步驟

`backend/.env` 不存在時會由 `.env.example` 建立；完成後仍需填入自己的 Gemini
或 Groq API key。

常用選項：

```bash
# 包含耗時的 RAG v2 清理、分類與建庫
./scripts/bootstrap.sh --with-rag

# 忽略快取，重跑所有選定步驟
./scripts/bootstrap.sh --force

# 只準備後端與前端，不處理 FHIR
./scripts/bootstrap.sh --skip-fhir

# 個別略過元件
./scripts/bootstrap.sh --skip-backend
./scripts/bootstrap.sh --skip-frontend
```

若 Python 執行檔名稱不同：

```bash
PYTHON_BIN=/path/to/python3.12 ./scripts/bootstrap.sh
```

建制狀態只保存在被 Git 忽略的 `.build-state/`。FHIR package 狀態與 PostgreSQL
volume 一起保存，因此移除資料庫後會重新安裝，不會被本機 cache 誤判。

各元件的手動步驟：

- [後端](../backend/README.md)
- [前端](../frontend/README.md)
- [RAG](../backend/knowledge/README.md)
- [FHIR／術語](../backend/terminology/README.md)

## `start-smart.sh`

啟動完整本機 SMART on FHIR stack：

```bash
./scripts/start-smart.sh
```

腳本會檢查 `backend/.env`、RAG 索引、embedding model cache 及後端
`/api/v1/health`。完整前置條件、入口與停止方式請見
[smart-app/README.md](../smart-app/README.md)。
