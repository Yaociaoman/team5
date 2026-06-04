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

