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

    cypher_file = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "databases", "graph", "seed.cypher")
    )

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # 0. Execute seed.cypher to apply constraints, indexes, and static topologies
        if os.path.exists(cypher_file):
            with open(cypher_file, 'r', encoding='utf-8') as f:
                cypher_content = f.read()
            # Split by semicolon to run statements individually
            queries = [q.strip() for q in cypher_content.split(';') if q.strip()]
            for q in queries:
                session.run(q)
            print("  Executed databases/graph/seed.cypher")
        else:
            print("  Warning: databases/graph/seed.cypher not found.")

        # --------------------------------------------------------------------------------
        # 遵守專案業務邏輯與架構規定 (Project-Specific Constraints & Rules)
        # 條件 3: 地鐵換線時間 - 不考慮地鐵站內換線時間，因此不建立額外的站內轉乘延遲邊。
        # 條件 5: 車站 ID 格式 - station_id 雖然在 RDB 設為 VARCHAR(10)，在此處視為 String (如 'MS01') 儲存。
        # 條件 6: 時刻表與停靠站設計 - 停靠站關聯表在 RDB 實作，Neo4j 中則以 CONNECTED_TO 邊表達物理相鄰關係。
        # --------------------------------------------------------------------------------

        # 1. 動態建立地鐵站點 (Metro Stations)
        session.run("""
        UNWIND $metro_stations AS m
        MERGE (n:Station:MetroStation {station_id: m.station_id})
        SET n.name = m.name,
            n.lines = m.lines,
            n.is_interchange_national_rail = m.is_interchange_national_rail
        """, metro_stations=metro_stations)
        print("  Dynamically created Metro Station nodes")

        # 2. 動態建立火車站點 (National Rail Stations)
        session.run("""
        UNWIND $rail_stations AS r
        MERGE (n:Station:NationalRailStation {station_id: r.station_id})
        SET n.name = r.name,
            n.lines = r.lines,
            n.is_interchange_metro = r.is_interchange_metro
        """, rail_stations=rail_stations)
        print("  Dynamically created National Rail Station nodes")

        # 3. 動態建立地鐵相鄰站點連線 (Metro Links)
        session.run("""
        UNWIND $metro_stations AS m
        MATCH (src:Station:MetroStation {station_id: m.station_id})
        UNWIND m.adjacent_stations AS adj
        MATCH (dest:Station:MetroStation {station_id: adj.station_id})
        MERGE (src)-[rel:METRO_LINK {line: adj.line}]->(dest)
        SET rel.duration_minutes = adj.travel_time_min,
            rel.fare = 0.30
        """, metro_stations=metro_stations)
        print("  Dynamically created Metro relationships")

        # 4. 動態建立火車相鄰站點連線 (National Rail Links)
        session.run("""
        UNWIND $rail_stations AS r
        MATCH (src:Station:NationalRailStation {station_id: r.station_id})
        UNWIND r.adjacent_stations AS adj
        MATCH (dest:Station:NationalRailStation {station_id: adj.station_id})
        MERGE (src)-[rel:RAIL_LINK {line: adj.line}]->(dest)
        SET rel.duration_minutes = adj.travel_time_min,
            rel.fare_standard = 1.50,
            rel.fare_first = 2.50
        """, rail_stations=rail_stations)
        print("  Dynamically created National Rail relationships")

        # 5. 動態建立跨系統步行轉乘連線 (Transfer Links between Metro and Rail)
        # 嚴格使用 TRANSFER 與 walking_time_minutes 以對應 seed.cypher 裡的拓撲定義
        session.run("""
        UNWIND $metro_stations AS m
        WITH m WHERE m.is_interchange_national_rail = true AND m.interchange_national_rail_station_id IS NOT NULL
        MATCH (ms:Station:MetroStation {station_id: m.station_id})
        MATCH (rs:Station:NationalRailStation {station_id: m.interchange_national_rail_station_id})
        MERGE (ms)-[rel1:TRANSFER]->(rs)
        SET rel1.walking_time_minutes = 5
        MERGE (rs)-[rel2:TRANSFER]->(ms)
        SET rel2.walking_time_minutes = 5
        """, metro_stations=metro_stations)
        print("  Dynamically created Transfer relationships (Walking transfers)")

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
