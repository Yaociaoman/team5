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
    
    try:
        with driver.session() as session:

            session.run("MATCH (n) DETACH DELETE n")
            print("  Cleared existing graph data")

            # 1. Metro Station nodes
            session.run("""
            UNWIND $metro_stations AS m
            MERGE (n:Station:MetroStation {station_id: m.station_id})
            SET n.name  = m.name,
                n.lines = m.lines,
                n.zone  = m.zone
            """, metro_stations=metro_stations)
            c = session.run("MATCH (n:MetroStation) RETURN count(n) AS c").single()["c"]
            print(f"  Created {c} MetroStation nodes")

            # 2. Rail Station nodes
            session.run("""
            UNWIND $rail_stations AS r
            MERGE (n:Station:RailStation {station_id: r.station_id})
            SET n.name  = r.name,
                n.lines = r.lines,
                n.zone  = r.zone
            """, rail_stations=rail_stations)
            c = session.run("MATCH (n:RailStation) RETURN count(n) AS c").single()["c"]
            print(f"  Created {c} RailStation nodes")

            # 3. Metro edges
            session.run("""
            UNWIND $metro_stations AS m
            MATCH (src:MetroStation {station_id: m.station_id})
            UNWIND m.adjacent_stations AS adj
            MATCH (dest:MetroStation {station_id: adj.station_id})
            MERGE (src)-[rel:METRO_LINK {line: adj.line}]->(dest)
            SET rel.travel_time_min = adj.travel_time_min,
                rel.fare_standard   = 0.30,
                rel.fare_first      = 0.30
            """, metro_stations=metro_stations)
            c = session.run("MATCH ()-[r:METRO_LINK]->() RETURN count(r) AS c").single()["c"]
            print(f"  Created {c} METRO_LINK relationships")

            # 4. Rail edges
            session.run("""
            UNWIND $rail_stations AS r
            MATCH (src:RailStation {station_id: r.station_id})
            UNWIND r.adjacent_stations AS adj
            MATCH (dest:RailStation {station_id: adj.station_id})
            MERGE (src)-[rel:RAIL_LINK {line: adj.line}]->(dest)
            SET rel.travel_time_min = adj.travel_time_min,
                rel.fare_standard   = 1.50,
                rel.fare_first      = 2.50
            """, rail_stations=rail_stations)
            c = session.run("MATCH ()-[r:RAIL_LINK]->() RETURN count(r) AS c").single()["c"]
            print(f"  Created {c} RAIL_LINK relationships")

            # 5. Interchange edges (Metro → Rail)
            session.run("""
            UNWIND $metro_stations AS m
            WITH m WHERE m.is_interchange_national_rail = true
                     AND m.interchange_national_rail_station_id IS NOT NULL
            MATCH (ms:MetroStation {station_id: m.station_id})
            MATCH (rs:RailStation  {station_id: m.interchange_national_rail_station_id})
            MERGE (ms)-[r1:INTERCHANGE_TO]->(rs)
            SET r1.travel_time_min = 5, r1.walk_time_min = 5,
                r1.fare_standard = 0.0, r1.fare_first = 0.0
            MERGE (rs)-[r2:INTERCHANGE_TO]->(ms)
            SET r2.travel_time_min = 5, r2.walk_time_min = 5,
                r2.fare_standard = 0.0, r2.fare_first = 0.0
            """, metro_stations=metro_stations)

            # 6. Interchange edges (Rail → Metro)
            session.run("""
            UNWIND $rail_stations AS r
            WITH r WHERE r.is_interchange_metro = true
                     AND r.interchange_metro_station_id IS NOT NULL
            MATCH (rs:RailStation  {station_id: r.station_id})
            MATCH (ms:MetroStation {station_id: r.interchange_metro_station_id})
            MERGE (rs)-[r1:INTERCHANGE_TO]->(ms)
            SET r1.travel_time_min = 5, r1.walk_time_min = 5,
                r1.fare_standard = 0.0, r1.fare_first = 0.0
            MERGE (ms)-[r2:INTERCHANGE_TO]->(rs)
            SET r2.travel_time_min = 5, r2.walk_time_min = 5,
                r2.fare_standard = 0.0, r2.fare_first = 0.0
            """, rail_stations=rail_stations)
            c = session.run("MATCH ()-[r:INTERCHANGE_TO]->() RETURN count(r) AS c").single()["c"]
            print(f"  Created {c} INTERCHANGE_TO relationships")

    except Exception as e:
        print(f"\n  ERROR during seeding: {e}")
        raise
    finally:
        driver.close()

    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
