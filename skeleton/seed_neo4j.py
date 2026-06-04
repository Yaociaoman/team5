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
        # Project-Specific Constraints & Rules
        # Condition 3: Subway Transfer Time - In-station transfer time is not considered; 
        #              therefore, no additional in-station transfer delay edges are created.
        # Condition 5: Station ID Format - Although station_id is defined as VARCHAR(10) in the RDB, 
        #              it is stored here as a String (e.g., 'MS01').
        # Condition 6: Timetable & Stop Design - The stop association table is implemented in the RDB, 
        #              while the physical adjacency relationship is expressed using CONNECTED_TO edges in Neo4j.
        # --------------------------------------------------------------------------------
        
        # 1. Dynamically Create Metro Stations
        session.run("""
        UNWIND $metro_stations AS m
        MERGE (n:MetroStation {station_id: m.station_id})
        SET n.name = m.name,
            n.lines = m.lines,
            n.zone  = m.zone
        """, metro_stations=metro_stations)
        print(f"  Created {len(metro_stations)} MetroStation nodes")

        # 2. 動態建立火車站點 (National Rail Stations)
        session.run("""
        UNWIND $rail_stations AS r
        MERGE (n:RailStation {station_id: r.station_id})
        SET n.name = r.name,
            n.lines = r.lines,
            n.zone  = r.zone
        """, rail_stations=rail_stations)
        print(f"  Created {len(rail_stations)} RailStation nodes")
        
        # 3. Dynamically Create Metro Adjacent Station Links (Metro Links)
        for s in metro_stations:
            for adj in s.get("adjacent_stations", []):
                session.run(
                    "MATCH (a:MetroStation {station_id: $from_id}) "
                    "MATCH (b:MetroStation {station_id: $to_id}) "
                    "MERGE (a)-[r:METRO_LINK {line: $line}]->(b) "
                    "SET r.travel_time_min = $time, r.fare_usd = $fare",
                    from_id=s["station_id"],
                    to_id=adj["station_id"],
                    line=adj.get("line", ""),
                    time=adj.get("travel_time_min", 0),
                    fare=adj.get("fare_usd", 0.0),
                )
        print(f"  Created METRO_LINK relationships")

        # 4. Dynamically Create National Rail Adjacent Station Links (National Rail Links)
        for s in rail_stations:
            for adj in s.get("adjacent_stations", []):
                session.run(
                    "MATCH (a:RailStation {station_id: $from_id}) "
                    "MATCH (b:RailStation {station_id: $to_id}) "
                    "MERGE (a)-[r:RAIL_LINK {line: $line}]->(b) "
                    "SET r.travel_time_min = $time, r.fare_usd = $fare",
                    from_id=s["station_id"],
                    to_id=adj["station_id"],
                    line=adj.get("line", ""),
                    time=adj.get("travel_time_min", 0),
                    fare=adj.get("fare_usd", 0.0),
                )
        print(f"  Created RAIL_LINK relationships")

        # 5. Dynamically Create Cross-System Walking Transfer Links (Transfer Links between Metro and Rail)
        # Create bidirectional INTERCHANGE relationships between metro and rail stations
        # walk_time_min represents the average walking time between platforms
        interchange_count = 0
        for s in metro_stations:
            if s.get("is_interchange_national_rail") and s.get("interchange_national_rail_station_id"):
                metro_id = s["station_id"]
                rail_id  = s["interchange_national_rail_station_id"]
                # Metro → Rail
                session.run(
                    "MATCH (m:MetroStation {station_id: $metro_id}) "
                    "MATCH (r:RailStation  {station_id: $rail_id}) "
                    "MERGE (m)-[i:INTERCHANGE {walk_time_min: 5}]->(r)",
                    metro_id=metro_id, rail_id=rail_id,
                )
                # Rail → Metro (reverse direction)
                session.run(
                    "MATCH (m:MetroStation {station_id: $metro_id}) "
                    "MATCH (r:RailStation  {station_id: $rail_id}) "
                    "MERGE (r)-[i:INTERCHANGE {walk_time_min: 5}]->(m)",
                    metro_id=metro_id, rail_id=rail_id,
                )
                interchange_count += 2
        print(f"  Created {interchange_count} INTERCHANGE relationships")

        # 從 Rail 出發的轉乘設定（確保雙向對應無遺漏）
        session.run("""
        UNWIND $rail_stations AS r
        WITH r WHERE r.is_interchange_metro = true AND r.interchange_metro_station_id IS NOT NULL
        MATCH (rs:Station:NationalRailStation {station_id: r.station_id})
        MATCH (ms:Station:MetroStation {station_id: r.interchange_metro_station_id})
        MERGE (rs)-[rel1:INTERCHANGE_TO]->(ms)
        SET rel1.travel_time_min = 5,
            rel1.fare = 0.0,
            rel1.fare_standard = 0.0,
            rel1.fare_first = 0.0
        MERGE (ms)-[rel2:INTERCHANGE_TO]->(rs)
        SET rel2.travel_time_min = 5,
            rel2.fare = 0.0,
            rel2.fare_standard = 0.0,
            rel2.fare_first = 0.0
        """, rail_stations=rail_stations)
        print("  Dynamically created Transfer relationships (Walking transfers)")

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
