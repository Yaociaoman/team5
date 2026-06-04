// ==========================================
// Graph Database Schema (Constraints & Indexes)
// ==========================================

// 1. Unique Constraints
// Ensure that the station_id for all stations is unique.
CREATE CONSTRAINT station_id_unique IF NOT EXISTS 
FOR (s:Station) REQUIRE s.station_id IS UNIQUE;

// Ensure that the station_id for all metro stations (MetroStation) is unique.
CREATE CONSTRAINT metro_station_id_unique IF NOT EXISTS 
FOR (m:MetroStation) REQUIRE m.station_id IS UNIQUE;

// Ensure that the station_id for all national rail stations (NationalRailStation) is unique.
CREATE CONSTRAINT national_rail_station_id_unique IF NOT EXISTS 
FOR (n:NationalRailStation) REQUIRE n.station_id IS UNIQUE;

// 2. Node Property Indexes
// Create indexes on station names to accelerate name search and matching.
CREATE INDEX station_name_index IF NOT EXISTS 
FOR (s:Station) ON (s.name);

CREATE INDEX metro_station_name_index IF NOT EXISTS 
FOR (m:MetroStation) ON (m.name);

CREATE INDEX national_rail_station_name_index IF NOT EXISTS 
FOR (n:NationalRailStation) ON (n.name);

// 3. Relationship Property Indexes (Optional, applicable to Neo4j 4.3+)
// Create indexes on connecting routes to speed up path searches for specific "lines".
CREATE INDEX metro_link_line_index IF NOT EXISTS 
FOR ()-[r:METRO_LINK]-() ON (r.line);

CREATE INDEX rail_link_line_index IF NOT EXISTS 
FOR ()-[r:RAIL_LINK]-() ON (r.line);

