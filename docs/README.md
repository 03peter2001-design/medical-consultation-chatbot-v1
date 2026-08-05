# 專案文件

本目錄保存程式之外的契約、研究資料與工作規劃。

| 路徑 | 內容 |
| --- | --- |
| `openapi.json` | 由 FastAPI models 產生並提交版本控制的 API 契約 |
| `tasks/TODOs.md` | 細部工作清單 |
| `AMIE Series Review and Agentic AI Research Plan.pptx` | AMIE／Agentic AI 研究簡報 |
| `代理人AI.docx` | 代理人 AI 研究文件 |
| `../future.md` | 正式 SMART 臨床應用的架構構想 |
| `../devlog/` | 依日期保存的開發紀錄 |

## OpenAPI 維護

後端 request／response model 或 route 變更後，在 `backend/` 更新契約：

```bash
python -m scripts.export_openapi
python -m scripts.export_openapi --check
```

再到 `frontend/` 更新與驗證 TypeScript definitions：

```bash
npm run api:types
npm run api:check
```

`frontend/src/generated/api.d.ts` 是衍生檔，不應手動修改。正式 API 使用 `/v1`
前綴；未加版本的路徑只作為相容別名。

## 開發規劃

- [x] 將前端重構為 Vue 3 + Vite
- [x] 整合 SMART OAuth launch context 與完整 Vue 預問診流程
- [x] 將主訴、基本資料、一般病史與疾病問卷拆成獨立 JSON
- [x] 建立胸痛、頭痛、腹痛、共通與安全的 RAG v2 collections
- [x] 加入可選的 Gemini 中英 dual-query 檢索與失敗 fallback
- [x] 導入 ClinicalFact 白名單、版本化三路由疾病表與確定性投票
- [x] 加入安全題優先、投票區辨力選題、70% 停止條件與 24 輪轉交
- [ ] 完成 RAG 安全庫、低信心分類與黃金測試集的醫療專業審查
- [ ] 完成正式 SMART client registration、後端身分驗證、最小權限與稽核
- [ ] 建立醫師確認後的 FHIR 回寫、Provenance 與 AuditEvent 流程
- [ ] 由醫師審查並校準三路由疾病表權重與 SNOMED CT coding
- [ ] 建立經醫師審查的 self-play 資料與 MedGemma 微調流程

## 正式臨床應用方向

目前 SMART stack 是合成資料開發 sandbox，不代表已支援院方登入、健保卡驗證
或正式醫療部署。預計的長期邊界為：

```text
病患入口 → SMART／院方 OIDC → 後端安全 Session → FHIR 病歷預填
        → AMIE 問診 → 病患主動送出 → 醫師待處理佇列

醫師入口 → EHR Launch → 後端角色授權 → Patient／Encounter context
        → RAG、SNOMED 與規則工具
```

正式環境預計採後端 BFF：FHIR access token 只留在後端，瀏覽器使用 HttpOnly
Session cookie；API 依 patient、clinician 與 rule_admin 角色授權，並加入最小
FHIR scopes、HTTPS、CSRF、防護與集中稽核。

仍需院方確認 EHR／FHIR Server、SMART client registration、OIDC／SSO、launch
context、網域與 TLS、臨床資料庫、稽核、個資治理及第三方身分驗證。完整構想與
參考標準請見 [../future.md](../future.md)。
