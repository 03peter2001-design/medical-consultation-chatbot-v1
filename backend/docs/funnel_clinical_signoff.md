# 問診漏斗修正：待臨床簽核清單

本文列出 2026-08-09 一批漏斗修正中，**由工程判斷暫定、但必須由醫師簽核後才可上線**的內容。
純程式邏輯的修正（route scope、完診閘門、輪數預算等）不在此列。

目前 49 份新問卷與下列 route metadata 皆維持 `source_structured_provisional`
candidate：不在 `DISEASE_ROUTES`／分類器／病患問卷中執行。Promotion 會驗證
問卷來源與 route catalog SHA-256、reviewer、日期、逐路由核准及所有 blocking
review note；本文件本身不是簽核證明。

## 1. 路由的臨床領域對應（`domain/questionnaire_routes.json` 的 `clinical_domain`）

只有 `chest`、`headache`、`abdomen` 擁有疾病表與路由專屬紅旗規則。其餘 49 條路由原本
兩者皆無，因此 catalog 中暫擬所屬 Safety 領域；未簽核前不會生效。Fixed-order
候選路由即使日後核准問卷，也不會直接借用三痛疾病表產出鑑別診斷。

目前暫擬指定（12 條，其餘 37 條為 `null`）：

| 領域 | 借用該領域規則的路由 |
|---|---|
| chest | `cardiovascular_issues`、`respiratory_issues`、`syncope` |
| headache | `stroke`、`neurological_issues`、`dizziness`、`seizure_epilepsy`、`loss_of_consciousness` |
| abdomen | `gynecological_issues`、`genitourinary_system_problems`、`vaginal_bleeding`、`obstetric_issues` |

**需要確認**：
- `syncope` 歸 chest（以心因性昏厥為先）是否恰當，或應同時涵蓋 headache。
- `dizziness` 歸 headache 是否足夠——周邊性眩暈與後循環中風的鑑別是否需要獨立疾病表。
- 其餘 37 條 `null` 路由中，是否有應該補上領域的（例如 `bleeding`、`weakness`、`fever`）。

## 2. 路由 disposition（同一份檔案的 `disposition`）

以下配對在臨床上相近，但目前處置不同，且分流完全取決於病人用詞：

| 病人講法 | 路由 | disposition |
|---|---|---|
| 不省人事／叫不醒 | `loss_of_consciousness` | urgent |
| 暈倒／昏倒 | `syncope` | questionnaire |
| 半身無力／嘴歪 | `stroke` | urgent |
| 無力／全身無力 | `weakness` | questionnaire |
| 嚴重外傷 | `trauma` | handoff |
| 跌倒 | `fall` | questionnaire |

**這一批未核准任何 disposition**，因為升降級屬臨床政策而非工程判斷；candidate
不會進入病患流程。靜態測試仍檢查暫擬關鍵字不會意外由較嚴格類別降級，目前僅
保留兩個語意不同的 containment 例外（`針刺傷` 不是 `刺傷`、`heatstroke` 不是
`stroke`），但這不構成臨床簽核。

## 3. 疾病表的權重與 rule-out 線索

疾病表由 `scripts/build_disease_profiles.py` 以 RAG + 離線模型一次性產生，帶有
`corpus_hash` 與 `generated_at` 的出處標記。**因此沒有手動改動已部署的表**——手寫臨床
權重會讓內容看起來像來自文獻管線，實際卻不是。

改的是產生器：
- 權重不再一律壓成 1，改為 1／2／3 三級（3 = 近乎特異，2 = 明顯鑑別，1 = 常見伴隨）。
- 每個 `must_not_miss` profile 至少要有一條 `status="absent"` 的 rule-out 線索。

現存欠債（`amie.disease_profiles.profile_quality_report` 可隨時查詢，並由
`tests/test_disease_funnel_integrity.py` 鎖住不得增加）：

- 33 個 profile 權重全部相同（chest 10、abdomen 14、headache 9，即全部）。
- 17 個 `must_not_miss` profile 沒有任何 rule-out 線索。

**需要決定**：重新產生三張疾病表的時機，以及產生後由誰逐條覆核並把
`review_status` 由 `provisional` 改為 `reviewed`。在那之前，否認症狀仍然無法降低票數。

## 4. 待核准的問卷選項

為了讓疾病表既有線索能被問到，曾暫擬三個選項；code review 後已從 active
`headache.json`／`abdomen.json` 撤回，未取得臨床簽核前不會上線。原本
`posterior_circulation_stroke` 的 5 條線索仍有 2 條、`gastrointestinal_bleeding`
的 4 條仍有 1 條無可問選項：

| 問卷 | 欄位 | 新增選項 | 對應 fact |
|---|---|---|---|
| headache | `associated` | 天旋地轉的暈眩 | `vertigo` |
| headache | `associated` | 走路不穩或站不住 | `gait_unsteadiness` |
| abdomen | `associated` | 大量出血或吐血 | `major_bleeding` |

**需要確認**：中文措辭、Safety 觸發與否定語意是否符合分診現場用語；核准後才可
重新加入 active questionnaire。

## 5. 已知的殘留限制

- **跨領域疾病競爭**：下壁心肌梗塞以上腹痛表現時，`abdomen` 疾病表沒有 ACS 這個
  profile，所以不會被列入鑑別。這需要在疾病表內容處理，不是引擎能補的。
- **49 條新問卷產不出任何 clinical fact**：它們的選項沒有 `semantic_options`，因此
  只能靠自由文字經語意抽取產生證據。要讓這些路由真正進入漏斗，需要逐份補對應。
- **`safety_rules.json` 的 `route_keywords` 已是死設定**：關鍵字的唯一真實來源已改為
  `domain/questionnaire_routes.json`，但驗證器仍要求它與 `supported_routes` 一致。
- **多主訴共用同一份輪數預算**：目前為各路由 budget 相加，若認為多主訴病人應更早轉交
  人工，改 `AMIEEngine._session_turn_budget` 即可。
