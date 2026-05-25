// ==========================================
// Graph Database Schema (Constraints & Indexes)
// ==========================================

// 1. 唯一性約束 (Unique Constraints)
// 確保所有車站 (Station) 的 station_id 唯一
CREATE CONSTRAINT station_id_unique IF NOT EXISTS 
FOR (s:Station) REQUIRE s.station_id IS UNIQUE;

// 確保捷運車站 (MetroStation) 的 station_id 唯一
CREATE CONSTRAINT metro_station_id_unique IF NOT EXISTS 
FOR (m:MetroStation) REQUIRE m.station_id IS UNIQUE;

// 確保火車站 (NationalRailStation) 的 station_id 唯一
CREATE CONSTRAINT national_rail_station_id_unique IF NOT EXISTS 
FOR (n:NationalRailStation) REQUIRE n.station_id IS UNIQUE;

// 2. 節點屬性索引 (Node Property Indexes)
// 針對車站名稱建立索引，加速名稱搜尋與比對
CREATE INDEX station_name_index IF NOT EXISTS 
FOR (s:Station) ON (s.name);

CREATE INDEX metro_station_name_index IF NOT EXISTS 
FOR (m:MetroStation) ON (m.name);

CREATE INDEX national_rail_station_name_index IF NOT EXISTS 
FOR (n:NationalRailStation) ON (n.name);

// 3. 關聯屬性索引 (Relationship Property Indexes) (可選，適用於 Neo4j 4.3+)
// 針對連接路線建立索引，加快針對特定「路線 (line)」的路徑搜尋
CREATE INDEX connected_to_line_index IF NOT EXISTS 
FOR ()-[r:CONNECTED_TO]-() ON (r.line);

// 備註：此 Cypher 腳本可透過 Neo4j Browser 執行，或由後端程式在啟動時自動套用。
// 依據專案規範，車站 ID 如 "MS01" 統一為 VARCHAR(10) (在關聯式資料庫中)，
// 圖形資料庫的 station_id 也需直接對應這些格式進行儲存。
