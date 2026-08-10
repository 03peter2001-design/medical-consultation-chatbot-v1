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

## 5. 未接線的問卷選項（active 路由，78 個可選答案）

已核准的三痛問卷與共用病史有 78 個選項沒有 `semantic_options` 對應。
病人被問、答案被保存、醫師看得到文字，但這些答案不會產生 fact，因此
本身無法影響疾病投票，也不會貢獻該題的 disease-vote utility。若欄位已被
`required_fields` 或 `priority_fields` 列入，仍可因政策而保留在問診中；不能把「無
fact」直接等同於「不會被問」。其中也包含「沒有」等可能合理保持未知的選項，
是否應產生否定 fact 須由臨床審查決定。（`basic.gender`／`blood_type` 另 7 項身分
欄位經由 `condition` 使用，不計入。）

缺口最大的幾處：

| 問卷 | 欄位 | 未接線 | 臨床意義 |
|---|---|---|---|
| chest | `cardio` | 16／16 | 心肌梗塞、支架、主動脈剝離、肺栓塞**病史**完全無法進入胸痛鑑別 |
| chest | `surgery` | 12／12 | 繞道、支架、人工血管置換同上 |
| headache | `neuro` | 6／9 | 中風、腦出血、腦部腫瘤病史無法進入頭痛鑑別 |
| headache | `surgery` | 7／7 | 動脈瘤夾閉、腦部放射線治療同上 |
| history | `chronic` | 7／7 | 糖尿病、肝硬化、癌症等共病對所有路由皆無作用 |
| history | `smoke` | 3／3 | 吸菸狀態對胸痛無作用 |

**未提出具體對應內容**：新增 fact code 與線索權重屬第 3 節同一類臨床決策，且需
與疾病表重新產生一併規劃（現行三張疾病表沒有任何風險因子線索，即使問卷接線了
也無處投票）。此節僅記錄缺口與量測方式。

量測與防止惡化：`tests/test_disease_funnel_integrity.py::QuestionnaireWiringDebtTests`
鎖定欄位與具體選項的明確 baseline；既有缺口可減少，但不能靠其他欄位的
修正來抵銷新增的未接線選項。

## 6. 一般病史可能完全不被詢問（待臨床政策決定）

`smoke`、`chronic`、`past_meds` 不在任何路由的 `required_fields`，且因為第 5 節的
未接線問題，`question_utility` 一律為 0。結果是它們只有在問診「剛好還沒結束」時
才會被問到。

`chronic_detail` 也不屬於 required，且自由文字題的靜態 `question_utility` 為 0；
但它只會在 `chronic` 選了自體免疫疾病、癌症或其他時才適用，若實際被問，
答案仍會經語意抽取產生 fact。因此它是另一個「可能在出現前就早停」的條件式
欄位，不與上述三個永適用的一般病史欄位混為同一量測。

實測（`scripts/measure_interview_length.py` 與 funnel behaviour 測試，合成答案）：

| 病人答題方式 | 結果 |
|---|---|
| 一律選第一個選項 | 18 題完診，抽菸／慢性病／過去用藥**都有問到** |
| 一律選最後一個選項 | **6 題完診，三者都沒問到** |

同一份胸痛問卷，只因為病人選了不同選項，就決定了系統會不會問吸菸史。

**需要決定**：是否把 `smoke`／`chronic`／`past_meds` 加入三痛路由的
`required_fields`。這會改變完診條件（§7 高風險），因此未逕行修改。
行為已由 `tests/test_funnel_behavior.py::GeneralHistoryRetentionTests` 鎖定，
政策修正後需一併更新該測試。

## 7. 已知的殘留限制

- **跨領域疾病競爭**：下壁心肌梗塞以上腹痛表現時，`abdomen` 疾病表沒有 ACS 這個
  profile，所以不會被列入鑑別。這需要在疾病表內容處理，不是引擎能補的。
- **49 條新問卷仍未接入 runtime facts**：疾病名稱導向 Gemini＋RAG pipeline 已在
  `questionnaire_drafts/clinical_artifacts/v1/20260810-gemini-disease-rag-v8/` 產生
  provisional overlay（431 fact proposals、344 個 exact-choice semantic mappings、
  118 profiles、82 Safety candidates），但不會回填 active questionnaire。Manifest
  仍列 45 個 profile 缺口、16 條無 Safety 路徑、6 條 evidence insufficient、8 個
  critical review notes，以及大量 citation evidence-pack 修補／不可達 fact 裁切；
  因此固定 `runtime_eligible=false`、`clinical_review_ready=false`。上線前仍需逐 route
  臨床審查、gold cases、跨 artifact composite signoff 與原子 publisher，不能使用現有
  questionnaire-only promoter。
- **`safety_rules.json` 的 `route_keywords` 已是死設定**：關鍵字的唯一真實來源已改為
  `domain/questionnaire_routes.json`，但驗證器仍要求它與 `supported_routes` 一致。
- **多主訴共用同一份輪數預算**：目前為各路由 budget 相加，若認為多主訴病人應更早轉交
  人工，改 `AMIEEngine._session_turn_budget` 即可。
