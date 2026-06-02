# AI Session Context — TransitFlow

**How to use this file:**
在每次開啟 AI 新對話時，請先完整複製 `code_regulation.md`，接著複製本檔案內容貼給 AI。這能讓 AI 了解專案最新的開發進度與架構共識。

---
# 專案當前開發狀態 (Current Progress)
* **圖資料庫等冪性 (Idempotency)：** `seed_neo4j.py` 中的節點與關係建立已全面改用 `MERGE` 與 `SET`，確保多次執行不會產生重複的「影子節點」。
* **圖形演算法 (Graph Algorithms)：** `queries.py` 已實作完成基於 APOC 的各項進階路徑搜尋（最快路徑、最便宜路徑、避開特定節點、跨網轉乘、故障波及漣漪）。
* **Cypher 語法規範：** Cypher 語句中的註解嚴格使用 `//`，禁止使用 Python 風格的 `#` 以免在查詢執行時引發 SyntaxError。

---
# 圖資料庫資料匯入 (Graph DB Seeding)
**Context:**
1. 地鐵與國鐵節點標籤分別為 `MetroStation` 與 `NationalRailStation`，皆繼承 `Station` 標籤。
2. 節點間的關係：地鐵使用 `METRO_LINK`，國鐵使用 `RAIL_LINK`，跨系統轉乘使用雙向的 `INTERCHANGE_TO`。
3. 匯入資料時一律使用 `MERGE` 確認節點/關係是否存在，並搭配 `SET` 進行屬性更新。

` skeleton/seed_neo4j.py `
```python
# 範例：建立節點與關聯 (使用 MERGE 保證等冪性)
session.run("""
UNWIND $metro_stations AS m
MERGE (n:Station:MetroStation {station_id: m.station_id})
SET n.name = m.name, 
    n.lines = m.lines,
    n.is_interchange_national_rail = m.is_interchange_national_rail
""", metro_stations=metro_stations)

session.run("""
UNWIND $metro_stations AS m
MATCH (src:MetroStation {station_id: m.station_id})
UNWIND m.adjacent_stations AS adj
MATCH (dest:MetroStation {station_id: adj.station_id})
MERGE (src)-[rel:METRO_LINK {line: adj.line}]->(dest)
SET rel.travel_time_min = adj.travel_time_min,
    rel.fare = 0.30
""", metro_stations=metro_stations)
```

---
# 圖資料庫查詢實作 (Graph DB Queries)
**Context:**
1. **防呆與預設值：** 若圖形中兩站不連通（APOC 找不到路徑），必須回傳合約定義的空列表或預設字典結構，避免 Agent 崩潰。
2. **動態艙等權重 (`query_cheapest_route`)：** 根據 `fare_class` 參數動態決定 `$weight_property`（如 `fare_standard`, `fare_first`），並帶入 `apoc.algo.dijkstra` 計算最便宜路徑。
3. **避開特定中繼站 (`query_alternative_routes`)：** 使用 `apoc.path.expandConfig`，透過 `blacklistNodes: [avoid]` 參數嚴格避開指定節點，並以 `limit` 限制回傳路徑條數。
4. **跨網轉乘路徑 (`query_interchange_path`)：** 透過組合過濾器 `METRO_LINK|RAIL_LINK|INTERCHANGE_TO` 讓 Dijkstra 演算法能在兩種網路間穿梭。
5. **故障漣漪邊界條件 (`query_delay_ripple`)：** 已完善處理邊界條件：當 `hops=0` 時，僅回傳查詢的故障車站本身，不再擴展任何鄰居節點。

` databases/graph/queries.py `
```python
# 範例：動態權重與 APOC Dijkstra
cypher_query = """
MATCH (start:Station {station_id: $origin_id})
MATCH (end:Station {station_id: $destination_id})
// 權重欄位 $weight_property 可依艙等動態代入 'fare_standard' 或 'fare_first'
CALL apoc.algo.dijkstra(start, end, $rel_filter, $weight_property, 0.0) 
YIELD path, weight
RETURN weight, [n IN nodes(path) | n.station_id] AS station_ids
"""

# 範例：處理 hops=0 邊界條件
if hops == 0:
    return [{
        "station_id": record["station_id"],
        "name": record["name"],
        "hops_away": 0,
        "lines_affected": []
    }]
```
