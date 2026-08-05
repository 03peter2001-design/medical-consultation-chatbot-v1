# FHIR、TW Core 與 SNOMED CT

本目錄保存安裝 `tw.gov.mohw.twcore#1.0.0` 至 HAPI FHIR R4 所需的完整 FHIR
NPM package dependency closure。新的 clone 不需要額外的 HAPI Starter checkout，
安裝 packages 時也不依賴線上 FHIR package registry。

本機 Compose 使用 HAPI FHIR 8.8.0 與 PostgreSQL 16。完整 SNOMED CT 與 LOINC
不包含於 TW Core dependencies，必須由部署者另行合法取得。

## Reproducibility

`packages.lock.json` is the source of truth. It records installation order,
package name, exact version, manifest license value, relative archive path and
SHA-256 for every archive. `python -m scripts.install_twcore` checks every
manifest and hash before contacting HAPI.

The package set contains:

| Package | Version | Why it is included |
| --- | --- | --- |
| `hl7.fhir.r4.core` | 4.0.1 | FHIR R4 base definitions |
| `hl7.fhir.r4.examples` | 4.0.1 | SDC dependency |
| `hl7.fhir.uv.extensions.r4` | 5.2.0 | TW Core and terminology extensions |
| `hl7.terminology.r4` | 5.0.0 | IPS-pinned terminology dependency |
| `fhir.dicom` | 2022.4.20221006 | IPS transitive dependency |
| `hl7.fhir.uv.ips` | 1.1.0 | TW Core direct dependency |
| `hl7.fhir.uv.sdc` | 3.0.0 | TW Core direct dependency |
| `hl7.terminology.r4` | 7.0.0 | TW Core direct terminology dependency |
| `tw.gov.mohw.twcore` | 1.0.0 | Taiwan Core Implementation Guide |

Both terminology versions are intentional: IPS 1.1.0 pins 5.0.0 while TW Core
1.0.0 pins 7.0.0. HAPI stores FHIR packages by package name and version.

The TW Core archive was downloaded from
`https://packages.fhir.org/tw.gov.mohw.twcore/1.0.0`; the dependency archives
under `packages/` use the equivalent registry URL formed from each locked name
and version. The archive manifests label the HL7 and TW Core packages
`CC0-1.0`; the DICOM package manifest labels itself `free`.

## Install

The root Compose workflow starts HAPI, waits for it to become healthy and
installs the complete locked set:

```bash
docker compose -f compose.fhir.yml --profile setup up -d
docker compose -f compose.fhir.yml logs twcore-installer
```

請在 repository 根目錄執行。log 顯示 `Installed 9 locked FHIR packages` 即完成；
第一次建立 terminology index 可能需要數分鐘。`twcore-installer` 正常完成後會以
exit code 0 結束，HAPI 與 PostgreSQL 則繼續執行。資料保存在 Compose volume，
一般停止不會消失：

```bash
docker compose -f compose.fhir.yml down
```

Docker 仍需由 registry 拉取 compose 檔鎖定的 HAPI、PostgreSQL 與 Python
images，但安裝 TW Core packages 不需要額外下載。

The `setup` profile prevents an ordinary later `docker compose up -d` from
reinstalling the same large package set. The installer also writes the lock
SHA-256 to `Basic/twcore-package-set` in HAPI. A later installer run skips the
upload when that database marker still matches `packages.lock.json`; use
`--force` to reinstall intentionally.

對既有資料庫強制重新安裝鎖定套件：

```bash
docker compose -f compose.fhir.yml --profile setup run --rm twcore-installer \
  python -m scripts.install_twcore --server http://hapi:8080/fhir --force
```

For an already-running HAPI server:

```bash
cd backend
python -m scripts.install_twcore
```

Set `FHIR_BASE_URL` or pass `--server` when HAPI is not available at
`http://127.0.0.1:8080/fhir`. To verify local files without contacting HAPI:

```bash
cd backend
python -m scripts.install_twcore --verify-only
```

HAPI 預設只綁定 `127.0.0.1:8080`。若 port 已占用：

```bash
FHIR_PORT=18080 docker compose -f compose.fhir.yml --profile setup up -d
```

Compose 內的資料庫帳密只供本機開發，不可直接沿用至正式環境。

The extracted `twcore-1.0.0/` files are an unmodified application-facing subset
used to identify official system URIs and relevant profiles. The complete
archive is the file installed into HAPI.

## Scope

These archives reproduce the TW Core profiles, extensions, ValueSets,
CodeSystems and package dependencies. They do **not** contain the full LOINC or
SNOMED CT releases. TW Core references those external systems but does not
redistribute their complete terminology content. Full SNOMED CT validation
still requires a licensed release or terminology service, and full LOINC
validation requires a separately obtained LOINC release.

## Local SNOMED CT release

SNOMED CT is licensed content and is deliberately excluded from this
repository. Each developer or deployer must obtain an authorized International
RF2 Production ZIP from SNOMED International and place it in:

```text
backend/terminology/snomed/
```

Do not extract or commit the release. The repository ignores both RF2 ZIP files
and directories named like an extracted SNOMED CT release. Verify a local file
without contacting HAPI:

```bash
cd backend
python -m scripts.install_snomed --verify-only
```

啟動 HAPI 後，以 Compose installer 匯入：

```bash
docker compose -f compose.fhir.yml up -d postgres hapi
docker compose -f compose.fhir.yml --profile snomed run --rm snomed-installer
```

installer 會先驗證 ZIP 內的 RF2 Snapshot，再以 HAPI
`CodeSystem/$upload-external-code-system` 匯入 `http://snomed.info/sct`。如果
TW Core dependency 曾建立重複的 `content=not-present` SNOMED placeholder，
installer 只保留一筆；只要已有實際 terminology 內容，就不會自動刪除。

HAPI 接受上傳後會在背景建立 terminology index。installer 會等待 SNOMED CT
胸痛代碼 `29857009` 通過 `$validate-code` 才結束；同一 release 再次執行時會依
SHA-256 marker 跳過。授權檔只以唯讀方式掛載，不會加入 image 或 Git。

正常安裝會另外產生 `snomed/snomed-search.sqlite3`，供醫師端 SNOMED CT
查詢頁進行英文全文搜尋。若 HAPI 已經安裝完成而只缺搜尋索引，可執行：

```bash
python -m scripts.build_snomed_search_index \
  terminology/snomed/SnomedCT_InternationalRF2_PRODUCTION_20250701T120000Z.zip
```

RF2 ZIP、SQLite 搜尋索引及其暫存檔都屬本機授權資料，不得提交到 Git。

查詢頁的英文文字搜尋使用本機 RF2 SQLite 索引；純數字 concept ID 仍透過
HAPI `CodeSystem/$lookup` 驗證，避免大型 in-memory ValueSet expansion 限制。

## 疾病表 SNOMED CT 對照

醫師端固定疾病表的對照位於 `../amie/disease_data/snomed_codings.json`。複合
疾病方向可以含多個 coding，前端會逐一顯示。此檔目前對應 International
Edition `20250701`，其中 41 個代碼已由本機 HAPI `$validate-code` 驗證。

更新 RF2 或 mapping 後必須重新驗證並重啟後端，以清除快取的疾病表。術語代碼
有效不代表疾病表已完成臨床審查；醫師校準前仍維持 `provisional`。

## 前端與 SMART 整合

Vue 直接連接 HAPI 的開發設定請見 [../../frontend/README.md](../../frontend/README.md#fhir-直接連線僅限開發測試)。
正式流程應改用 SMART OAuth；本機整合方式請見
[../../smart-app/README.md](../../smart-app/README.md)。
