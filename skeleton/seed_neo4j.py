"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # --------------------------------------------------------------------------------
        # 遵守專案業務邏輯與架構規定 (Project-Specific Constraints & Rules)
        # 條件 3: 地鐵換線時間 - 不考慮地鐵站內換線時間，因此不建立額外的站內轉乘延遲邊。
        # 條件 5: 車站 ID 格式 - station_id 雖然在 RDB 設為 VARCHAR(10)，在此處視為 String (如 'MS01') 儲存。
        # 條件 6: 時刻表與停靠站設計 - 停靠站關聯表在 RDB 實作，Neo4j 中則以 CONNECTED_TO 邊表達物理相鄰關係。
        # --------------------------------------------------------------------------------

        # 1. 建立地鐵站點 (Metro Stations)
        session.run("""
        UNWIND $metro_stations AS m
        MERGE (n:Station:MetroStation {station_id: m.station_id})
        SET n.name = m.name,
            n.lines = m.lines,
            n.is_interchange_national_rail = m.is_interchange_national_rail
        """, metro_stations=metro_stations)
        print("  Created Metro Station nodes")

        # 2. 建立火車站點 (National Rail Stations)
        session.run("""
        UNWIND $rail_stations AS r
        MERGE (n:Station:NationalRailStation {station_id: r.station_id})
        SET n.name = r.name,
            n.lines = r.lines,
            n.is_interchange_metro = r.is_interchange_metro
        """, rail_stations=rail_stations)
        print("  Created National Rail Station nodes")

        # 3. 建立地鐵相鄰站點連線 (Metro Links)
        session.run("""
        UNWIND $metro_stations AS m
        MATCH (src:MetroStation {station_id: m.station_id})
        UNWIND m.adjacent_stations AS adj
        MATCH (dest:MetroStation {station_id: adj.station_id})
        MERGE (src)-[rel:METRO_LINK {line: adj.line}]->(dest)
        SET rel.travel_time_min = adj.travel_time_min,
            rel.fare = 0.30
        """, metro_stations=metro_stations)
        print("  Created Metro relationships")

        # 4. 建立火車相鄰站點連線 (National Rail Links)
        session.run("""
        UNWIND $rail_stations AS r
        MATCH (src:NationalRailStation {station_id: r.station_id})
        UNWIND r.adjacent_stations AS adj
        MATCH (dest:NationalRailStation {station_id: adj.station_id})
        MERGE (src)-[rel:RAIL_LINK {line: adj.line}]->(dest)
        SET rel.travel_time_min = adj.travel_time_min,
            rel.fare_standard = 1.50,
            rel.fare_first = 2.50
        """, rail_stations=rail_stations)
        print("  Created National Rail relationships")

        # 5. 建立跨系統步行轉乘連線 (Interchange Links between Metro and Rail)
        # 加入步行時間 5 分鐘作為預設轉乘成本，建立雙向的 INTERCHANGE_TO 關係
        session.run("""
        UNWIND $metro_stations AS m
        WITH m WHERE m.is_interchange_national_rail = true AND m.interchange_national_rail_station_id IS NOT NULL
        MATCH (ms:MetroStation {station_id: m.station_id})
        MATCH (rs:NationalRailStation {station_id: m.interchange_national_rail_station_id})
        MERGE (ms)-[rel1:INTERCHANGE_TO {type: 'walking'}]->(rs)
        SET rel1.travel_time_min = 5
        MERGE (rs)-[rel2:INTERCHANGE_TO {type: 'walking'}]->(ms)
        SET rel2.travel_time_min = 5
        """, metro_stations=metro_stations)
        print("  Created Interchange relationships (Walking transfers)")

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
