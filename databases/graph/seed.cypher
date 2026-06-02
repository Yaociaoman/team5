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
CREATE INDEX metro_link_line_index IF NOT EXISTS 
FOR ()-[r:METRO_LINK]-() ON (r.line);

CREATE INDEX rail_link_line_index IF NOT EXISTS 
FOR ()-[r:RAIL_LINK]-() ON (r.line);

// 備註：此 Cypher 腳本可透過 Neo4j Browser 執行，或由後端程式在啟動時自動套用。
// 依據專案規範，車站 ID 如 "MS01" 統一為 VARCHAR(10) (在關聯式資料庫中)，
// 圖形資料庫的 station_id 也需直接對應這些格式進行儲存。

// ==========================================
// Static Graph Topology Seed (Nodes & Relationships)
// ==========================================

// Create Sample Metro Stations
MERGE (m1:Station:MetroStation {station_id: 'MS01'})
  ON CREATE SET m1.name = 'Taipei Main Station', m1.city = 'Taipei'
MERGE (m2:Station:MetroStation {station_id: 'MS02'})
  ON CREATE SET m2.name = 'Zhongshan', m2.city = 'Taipei'

// Create Sample National Rail Stations
MERGE (n1:Station:NationalRailStation {station_id: 'NRS01'})
  ON CREATE SET n1.name = 'Taipei Main Station', n1.city = 'Taipei'
MERGE (n2:Station:NationalRailStation {station_id: 'NRS02'})
  ON CREATE SET n2.name = 'Banqiao', n2.city = 'New Taipei'

// Create Sample Metro Link
MERGE (m1)-[rm:METRO_LINK {line: 'Red Line'}]->(m2)
  ON CREATE SET rm.distance = 1.2, rm.duration_minutes = 3
MERGE (m2)-[rm_rev:METRO_LINK {line: 'Red Line'}]->(m1)
  ON CREATE SET rm_rev.distance = 1.2, rm_rev.duration_minutes = 3

// Create Sample Rail Link
MERGE (n1)-[rr:RAIL_LINK {line: 'West Coast Line'}]->(n2)
  ON CREATE SET rr.distance = 7.5, rr.duration_minutes = 10
MERGE (n2)-[rr_rev:RAIL_LINK {line: 'West Coast Line'}]->(n1)
  ON CREATE SET rr_rev.distance = 7.5, rr_rev.duration_minutes = 10

// Create Transfer Link between Metro and Rail at the same location
MERGE (m1)-[t:TRANSFER]->(n1)
  ON CREATE SET t.walking_time_minutes = 5
MERGE (n1)-[t_rev:TRANSFER]->(m1)
  ON CREATE SET t_rev.walking_time_minutes = 5
