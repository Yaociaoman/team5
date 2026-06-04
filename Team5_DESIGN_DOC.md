# IM2002 — Student Guide: Design Document Evaluation · /100

---

## Mark Summary

| Section | Max |
|---------|-----|
| Section 1 — Entity-Relationship Diagram | 25 |
| Section 2 — Normalisation Justification | 20 |
| Section 3 — Graph Database Design Rationale | 25 |
| Section 4 — Vector / RAG Design | 15 |
| Section 5 — AI Tool Usage Evidence | 10 |
| Section 6 — Reflection & Trade-offs | 5 |
| **Total** | **100** |
| Task 6 Bonus — Section 7 (optional) | +15 |

---

## Section 1 — Entity-Relationship Diagram · /25

| Criterion | What earns full marks |
|-----------|-----------------------|
| All required entities represented in the diagram | Every entity needed to model the system is present in the diagram |
| Relationships shown with correct cardinality (1:N, M:N, etc.) | Every major relationship has a cardinality label directly on the diagram line |
| Attributes shown: at minimum PK, key FKs, and 2–3 representative data fields per entity | Each entity shows its PK, the FKs that link it to other entities, and at least two data attributes |
| Diagram is readable and professionally drawn (dbdiagram.io, draw.io, Lucidchart, or equivalent) | Clean layout; text is legible; a tool-generated diagram rather than a hand sketch |
| **Section 1 Total** | |

**Cardinality scoring (8 marks):** All major relationships correctly labelled = 8 ·
Most correct = 5–7 · Some missing or wrong = 2–4 · No cardinality shown = 0

> **Tip:** Cardinality labels must appear **on the diagram lines**, not only in a legend or text paragraph. A diagram that shows entity boxes and lines without cardinality notation scores 0 for that criterion.

---

## Section 2 — Normalisation Justification · /20

| Criterion | What earns full marks |
|-----------|-----------------------|
| Identifies and explains at least one 2NF or 3NF design decision (e.g., why schedule stops are in a junction table rather than an array column) | Identifies a real normalisation decision, names the normal form it achieves, and explains the functional dependency that motivated it |
| Discusses at least one deliberate de-normalisation trade-off with justification (or explains why full normalisation was preferred) | Either describes a de-normalisation choice with a performance or simplicity rationale, or explicitly argues that full normalisation was appropriate for this system |
| Discusses password hashing: algorithm chosen, why it was selected over alternatives, how salt is managed | Names the specific algorithm; explains *why* it is preferred over MD5/SHA-1 (cost factor, key stretching); explains how salt prevents rainbow-table attacks |
| Correct use of database terminology (functional dependency, candidate key, transitive dependency, etc.) | Terms used correctly and precisely, not just as decoration |
| **Section 2 Total** | |

**Normalisation scoring (8 marks):** Identifies a real 3NF decision with clear explanation = 7–8 ·
**Normalisation scoring:** Identifies a real 3NF decision with clear explanation = full marks · Identifies a decision but explanation is shallow = 20% deduction · Mentions normalisation but does not connect to the schema = 70% deduction · Missing = 0

**Password hashing scoring:** Names specific algorithm + explains why (not just "it is secure") + explains how salt works = full marks · Names algorithm without rationale = 50% deduction · Mentions hashing without algorithm = 80% deduction · Missing or plain-text = 0

> **Tip — password hashing:** Writing "we use argon2id because it is secure" earns 20% marks, not full. You must explain *why* argon2id is preferred over MD5/SHA-1. You must also explain how salt prevents two users with the same password from having the same hash (defeating rainbow-table lookups). Use appropriate examples in your explanation.

---

## Section 3 — Graph Database Design Rationale · /25

1. **概念模型設計與實體映射理由**
在 TransitFlow 系統中，我們將城市地鐵（M1–M4）和國家鐵路（NR1–NR2）組成的雙層交通網絡，建模為一個異質圖（Heterogeneous Graph）。

A. **節點設計 (Nodes)**
- `:Station`：基礎全域標籤，用於全域唯一性檢查與索引加速。
- `:MetroStation` 與 `:RailStation`：分別代表地鐵站與鐵路站。
- **【設計理由】**：車站是交通網絡的拓撲交匯點。將其建模為獨立「節點」而非邊上的屬性，是因為車站本身具備業務狀態（例如擁擠、延遲或封閉），節點化才能方便對其進行狀態變更。此外，分離標籤能讓 Cypher 查詢快速縮小搜尋範圍，避免全圖掃描。

B. **關係設計 (Relationships)**
- `[:METRO_LINK]` 與 `[:RAIL_LINK]`：代表地鐵與鐵路線路相鄰站點的物理連接。
- `[:INTERCHANGE_TO]`：代表跨網絡的同站步行轉乘通道。
- **【設計理由】**：將連接關係提升為一等公民（First-class citizen）。區分關係類型可讓演算法在純地鐵或純鐵路導航時，直接過濾掉無關的邊。而獨立出 `INTERCHANGE_TO` 關係，成功將「轉乘步行時間」解耦為獨立的邊權重，最短路徑演算法便能無縫計算轉乘成本，不需在節點內部寫複雜的條件跳躍邏輯。

C. **屬性設計 (Properties)**
- **節點屬性**：`station_id` (唯一碼)、`name` (站名)、`lines` (行經線路陣列，用於受災波及分析)、`zone` (計費區)。
- **關係屬性**：`line` (線路名)、`travel_time_min` (行車或轉乘時間)、`fare_standard` / `fare_first` (艙等票價)。
- **【設計理由】**：行車時間與票價是由「移動」產生的，成本屬於關係而非車站本身。車站節點存儲 `lines` 陣列，則能讓系統在某站故障時，立刻查出波及線路並向上層業務回報。

2. **節點標識決策 (Node Identification)**
我們統一指定 `station_id`（地鐵 "MS" 開頭，鐵路 "NR" 開頭）作為所有車站節點的唯一識別碼。
- **【選擇原因與實作保障】**：
  - **對接開銷低**：外部 API 與業務代碼皆以 `station_id` 為參數，直接以此為唯一識別能免去 Neo4j 原生內部 ID 的轉換開銷。
  - **前綴直接分流**：透過識別前綴，代碼層能直接推斷其所屬網絡，動態決定 Cypher 的標籤過濾。
  - **資料庫層保障**：在初始化（`graph/seed.cypher`）時已建立嚴格的唯一性約束與屬性索引，確保 $O(1)$ 查找速度並杜絕重複：
```cypher
CREATE CONSTRAINT station_id_unique IF NOT EXISTS FOR (s:Station) REQUIRE s.station_id IS UNIQUE;
CREATE CONSTRAINT metro_station_id_unique IF NOT EXISTS FOR (m:MetroStation) REQUIRE m.station_id IS UNIQUE;
```

3. **圖資料庫與關係資料庫之演算法對比論證**
對於路由（尋找最快/最便宜路徑、延遲分析）用例，圖資料庫不論在演算法或記憶體架構上皆完勝關係資料庫（RDB）：

A. **最短路徑用例：圖 Dijkstra 演算法 vs. SQL 遞歸 CTE**
- **圖資料庫（Neo4j + APOC Dijkstra）**：
  Neo4j 採用無索引遍歷（Index-free Adjacency），每個車站節點直接持有相鄰邊的記憶體指標。Dijkstra 演算法以優先佇列維護最小成本並沿指標步進，時間複雜度為 $O(|E| + |V| \log |V|)$。其搜尋空間僅限於連通拓撲，與全圖的總資料量無關。
- **關係資料庫（SQL 遞歸 CTE）**：
  RDB 必須依靠遞歸公用表表式（Recursive CTE）。在每一次遞歸的 JOIN 中，RDB 都必須拿 `to_station_id` 去 `connections` 表的 B+ Tree 索引裡做一次 $O(\log N)$ 的尋找，成本隨深度呈指數級放大。此外，為了解決交通網絡的「環路」問題，SQL 必須在記憶體裡幫每條路徑維護一個字串（如 `path_set`），容易導致路徑集爆炸、消耗大量 CPU 與記憶體拷貝開銷。

B. **延遲波動分析：圖 BFS vs. SQL 多重 Self-Join**
- **圖資料庫**：找出 $N$ 步內受波及的車站時（`query_delay_ripple`），Neo4j 執行原生廣度優先搜尋（BFS），直接從出事節點往外讀取指標，數到第 $N$ 層即停止，速度極快。
- **關係資料庫**：SQL 必須對同一張表進行 $N$ 次自我連接（Self-Join）或深層遞歸。當 $N \ge 3$ 時，執行計畫極易崩潰成全表掃描（Full Table Scan），產生巨大的磁碟 I/O 開銷。

4. **具體查詢類型之圖模型表達論證**
以下為系統中成功實作的兩個核心查詢函數，說明圖結構如何支持並精簡複雜的表達：

**查詢一：跨網絡轉乘路徑查詢 (Cross-Network Interchange Path)**
- **實作函數**：`query_interchange_path(origin_id, destination_id)`
- **結構論證**：地鐵與鐵路節點之間架設了 `[:INTERCHANGE_TO]` 關係，這打破了原本孤立的網絡邊界。
```cypher
MATCH (origin:MetroStation {station_id: $origin_id}), (dest:RailStation {station_id: $dest_id})
MATCH path = shortestPath((origin)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*]->(dest))
RETURN path, reduce(t = 0, r IN relationships(path) | t + coalesce(r.travel_time_min, 0)) AS total_time
```
利用 `|` 算子，圖遍歷器可以同時將地鐵、鐵路與轉乘通道視為通路。再透過 `reduce()` 函數，演算法能一邊走一邊累加關係上的搭車時間或轉乘步行時間。這種將「轉乘」實體化為邊的結構，讓最短路徑遍歷完全不需編寫網絡切換的邏輯判斷。

**查詢二：避開故障車站的替代路線 (Alternative Routes Avoiding a Station)**
- **實作函數**：`query_alternative_routes(origin_id, destination_id, avoid_station_id)`
- **結構論證**：系統需要為封閉車站規劃繞道方案，圖模型直接透過「路徑節點過濾與拓撲剪枝」來達成：
```cypher
MATCH (origin:Station {station_id: $origin_id}), (dest:Station {station_id: $dest_id})
MATCH path = allShortestPaths((origin)-[:METRO_LINK|RAIL_LINK*]->(dest))
WHERE NONE(n IN nodes(path) WHERE n.station_id = $avoid_id AND n.station_id <> $origin_id)
RETURN path LIMIT $limit
```
在 Neo4j 中，路徑是一等公民（`path` 變數）。透過 `nodes(path)` 抓出節點序列並搭配 `NONE(...)` 條件，圖引擎在記憶體中找路時，一旦發現潛在分支會觸碰故障的 `avoid_station_id`，就會在底層直接剪枝該拓撲分支（Pruning）。這種在結構層面直接剪枝的特性，比 SQL 需要生成所有連線再於最後過濾，效率高出許多。

---

## Section 4 — Vector / RAG Design · /15

**核心嵌入策略與餘弦相似度**
TransitFlow 採用餘弦相似度而非歐幾里得距離，來將使用者查詢與政策文件進行匹配。餘弦相似度計算的是高維空間中兩個向量之間的夾角，輸出值介於 -1 到 1 之間。它的關鍵特性在於完全獨立於向量的長度（magnitude），只關注方向是否一致。換句話說，就算兩個向量的長度差很多，只要它們指向同一個語義方向，餘弦相似度就會給出高分。
這對語義搜尋非常重要。舉例來說，使用者輸入一個簡短的查詢「退款資格」，而政策文件可能是包含大量細節的多段落長文。兩者的 token 數量差距很大，因此產生的向量長度也差很多。如果用歐幾里得距離來衡量，這個長度差異會直接壓低相似度分數，導致明明語義相關的文件被排在後面。餘弦相似度透過正規化消除這個問題，讓系統可以純粹根據「語義方向」來判斷相關性，而不是受文件長度影響。
**完整的 RAG 流程**
RAG 流程分成四個連續階段來回答使用者的問題：
第一步，使用者輸入的查詢字串會透過 llm.embed() 呼叫本地端的 nomic-embed-text 模型，轉換成 768 維的浮點數向量。
第二步，這個查詢向量會被傳進 PostgreSQL，由 pgvector 的 <=> 運算子執行餘弦距離搜尋。系統設定相似度門檻值為 0.5，並限制只回傳最相關的前 3 筆結果（LIMIT 3），避免把不相關的文件丟進後續流程。
第三步，檢索到的政策文件會被整理成包含標題、分類與最多 800 字元內容的純文字格式，方便後續嵌入提示詞。
第四步，這些文件會被包裹在一個嚴格的提示詞結構裡，明確標記為唯一的資訊來源，再連同使用者的原始問題一起送給 LLM 生成最終回答。這樣做是為了避免 LLM 自行「腦補」不在文件中的內容。
**嵌入維度限制與切換提供商的後果**
向量欄位的維度與嵌入模型是強綁定的關係。預設情況下，系統使用 Ollama 的 nomic-embed-text 模型產生 768 維向量，policy_documents 資料表的向量欄位被定義為 vector(768)，HNSW 索引也是針對這個維度建立的。
如果想切換成 Gemini（gemini-embedding-001），它輸出的是 3072 維向量。問題不會在切換或灌資料的時候報錯，而是在查詢時才爆炸——PostgreSQL 會因為查詢向量（3072 維）和儲存向量（768 維）維度不符而拋出錯誤，整個索引都會無法使用，RAG 系統完全癱瘓。
要正確切換提供商，必須依序執行：刪除原有資料表、重新建立欄位定義為 vector(3072) 的新資料表、重建 HNSW 索引，最後重新執行資料灌錄腳本。沒有辦法只換模型而不重建整個向量索引。

| **Section 4 Total** | |

> **Tip:** Explain the practical consequence of changing providers after seeding.

---

## Section 5 — AI Tool Usage Evidence · /10

**1.**
**Context :**
在執行資料庫初始化與灌錄腳本（seed_postgres.py）時，終端機反覆回傳 psycopg2.OperationalError: Connection refused 的連線錯誤。小組初期判斷為連線埠號（Port）或本機網路故障，在反覆修改埠號參數後仍無法順利解開連線死結。

**Prompt :**

「我的一直跑出個問題（Connection refused），但所以就算我要改 port num 我要去哪裡改才能變正確的？還是是我 localhost 的問題？... 一樣跑出這樣的資訊 到底為什麼？」

**Outcome:**
AI 指出連線被拒絕（Connection Refused）的根本原因並非網路介面故障，而是因為綱要結構檔（schema.sql）最末端的 CREATE INDEX IF NOT EXISTS ON 語法缺少了明確的索引名稱，導致 PostgreSQL 引擎在 Docker 背景進行初始化時引發語法解析錯誤並當場終止運行（Exited）。在 AI 的協助下，小組將該行語法修正為具名索引 idx_policy_embedding，使資料庫容器順利進入 Up (healthy) 狀態，成功恢復 host 監聽通道。
--
**2.**
**Context :**
在資料庫容器正常運作後，小組仍需精準對齊本機端（Host）與 Docker 容器內部（Container）的網路通訊埠，並確認大語言模型（LLM）微調工具鏈是否需要引入外部 API 憑證（API Key）。

**Prompt :**

「這是我的.env還是其實問題出在這裡嗎？ 我需要給他我的api key？ 還是其他原因... 這裡是我的config.py... 還是錯啊」

**Outcome:**
AI 協助小組校對了 docker-compose.yml 檔案中的埠號映射宣告 "- 5433:5432"。說明該語法代表 PostgreSQL 實體於容器內監聽 5432，但對 Mac 本機暴露的通訊大門為 5433。小組據此將 .env 內的 PG_PORT 參數統一修正為 5433 進行精確對齊。同時確認因專案配置 LLM_PROVIDER=ollama，其編排架構完全採用本地端（Local LLM）離線模型（Llama3.2），因此無須配置任何外部 Gemini 雲端憑證，成功精簡了環境配置。
--
**3.**
**Context :**
在進行交易 Ledger 資料灌錄時，系統在 payments 與 feedback 的執行邊界觸發了 ForeignKeyViolation 錯誤，提示：DETAIL: Key (booking_id)=(MT001) is not present in table "bookings"。經小組結構化分析，發現 Mock 資料源 payments.json 具有多型態（Polymorphic）特徵：其包含國鐵訂單（BK-）與地鐵乘車歷史（MT-）。然而原始 Schema 將 booking_id 設為非空（NOT NULL）且僅單向關聯至國鐵表，導致地鐵流水帳無法相容。在嘗試修正時，AI 給出了錯誤的 schema 變更指令。

**Prompt :**

AI 的錯誤指示： AI 漏掉了我們尚未執行 seed_users 與 seed_metro_travels 的系統狀態，便直接要求小組在 Terminal 執行 ALTER TABLE payments ADD COLUMN trip_id ...，此舉因未解除原本的非空約束，導致系統拋出欄位已存在的衝突報錯。
小組的糾正 Prompt： 「沒有成功耶，一樣是沒有顯示 not null。妳給的語法有問題，因為原本的表有 NOT NULL 限制，而且妳完全漏掉了 seed_postgres.py 裡面一開始連 seed_users 和 seed_metro_travels 都沒被執行到的 Bug！請幫我把 booking_id 的 NOT NULL 移除，並將 trip_id 設為外鍵關聯至地鐵歷史表，最後加上一個兩者互斥、剛好只能有一個來源為真的 CHECK 約束！」

**Outcome:**
I 被小組精準的資料庫邏輯糾正後，承認其未妥善處理 Polymorphic 重構的非空鎖定狀態。AI 重新為小組設計了具備強大防禦性的 Schema 重構語法：將 booking_id 變更為 DROP NOT NULL，追加 trip_id 外鍵，並實作檢查約束：CONSTRAINT chk_payments_single_source CHECK ((booking_id IS NOT NULL)::int + (trip_id IS NOT NULL)::int = 1)。在小組同步補齊 Python 端的資料流載入邏輯並重置磁區後，腳本順利通過交易邊界檢查，輸出 Database seeded successfully into 3NF schema. 的大功告成標誌。
--

**4.**
**Context :**
當本地端 Schema 修正完畢且 Seeding 通過後，小組欲執行 git pull 同步上游倉庫。然而因多人在不同分支同時提交（Commit）了資料庫腳本，導致 Git 觸發了非快速向前（Non-fast-forward）保護機制，本地端終端機被強制鎖定於背景進行自動合併的 Vim 編輯器介面中，開發進度受阻。

**Prompt :**

「Merge branch 'main' of https://github.com/ash-eeee/team5 ... Lines starting with '#' will be ignored, and an empty message aborts the commit. ~ ~ ~ 現在長這樣」

**Outcome:**
AI 指出此畫面為 Git 核心機制要求開發者確認合併日誌之標準安全行為。AI 引導小組利用非可視化退出指令：先按下 Esc 鍵確保退出編輯狀態，隨後輸入命令 :wq（寫入並退出）按下 Enter 鍵。小組成功解鎖終端機控制權，並藉由下達 git config pull.rebase false 設定團隊預設之合併策略，將組員的代碼資產與圖片完美融合進 MacBook 本地端中，達成了高效的分佈式團隊同步。

---

## Section 6 — Reflection & Trade-offs · /5

| Criterion | What earns full marks |
|-----------|-----------------------|
| Identifies at least two specific design decisions and explains the reasoning behind each | Two decisions named with clear reasoning — not vague ("we thought it was better"), but specific (e.g., "we chose SERIAL over UUID because our system is single-region and integer joins are faster") |
| Discusses one aspect that would be different in a production system | Names a concrete production concern (schema migrations, connection pooling, secret management, indexing strategy, etc.) and explains why it would need to change |
| **Section 6 Total** | |

**Design decisions scoring (3 marks):** Two specific decisions with clear reasoning = 3 ·
**Design decisions scoring:** Two specific decisions with clear reasoning = 3 · Vague decisions without reasoning = 1–2 · Missing = 0

**Production difference scoring:** Identifies a concrete production concern with explanation = 2 · Mentions something production-related without depth = 1 · Missing = 0

---