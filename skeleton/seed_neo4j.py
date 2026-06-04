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
        # Project-Specific Constraints & Rules
        # Condition 3: Subway Transfer Time - In-station transfer time is not considered; 
        #              therefore, no additional in-station transfer delay edges are created.
        # Condition 5: Station ID Format - Although station_id is defined as VARCHAR(10) in the RDB, 
        #              it is stored here as a String (e.g., 'MS01').
        # Condition 6: Timetable & Stop Design - The stop association table is implemented in the RDB, 
        #              while the physical adjacency relationship is expressed using CONNECTED_TO edges in Neo4j.
        # --------------------------------------------------------------------------------
       
        # 1. Dynamically create Metro Station nodes
        session.run("""
        UNWIND $metro_stations AS m
        MERGE (n:Station:MetroStation {station_id: m.station_id})
        SET n.name = m.name,
            n.lines = m.lines,
            n.is_interchange_national_rail = m.is_interchange_national_rail
        """, metro_stations=metro_stations)
        print("  Dynamically created Metro Station nodes")

        # 2. Dynamically create National Rail Station nodes
        session.run("""
        UNWIND $rail_stations AS r
        MERGE (n:Station:NationalRailStation {station_id: r.station_id})
        SET n.name = r.name,
            n.lines = r.lines,
            n.is_interchange_metro = r.is_interchange_metro
        """, rail_stations=rail_stations)
        print("  Dynamically created National Rail Station nodes")

        # 3. Dynamically Create Metro Links (Adjacent Station Connections)
        session.run("""
        UNWIND $metro_stations AS m
        MATCH (src:Station:MetroStation {station_id: m.station_id})
        UNWIND m.adjacent_stations AS adj
        MATCH (dest:Station:MetroStation {station_id: adj.station_id})
        MERGE (src)-[rel:METRO_LINK {line: adj.line}]->(dest)
        SET rel.travel_time_min = adj.travel_time_min,
            rel.fare = 0.30,
            rel.fare_standard = 0.30,
            rel.fare_first = 0.30
        """, metro_stations=metro_stations)
        print("  Dynamically created Metro relationships")

        # 4. Dynamically Create National Rail Links (Adjacent Station Connections)
        session.run("""
        UNWIND $rail_stations AS r
        MATCH (src:Station:NationalRailStation {station_id: r.station_id})
        UNWIND r.adjacent_stations AS adj
        MATCH (dest:Station:NationalRailStation {station_id: adj.station_id})
        MERGE (src)-[rel:RAIL_LINK {line: adj.line}]->(dest)
        SET rel.travel_time_min = adj.travel_time_min,
            rel.fare_standard = 1.50,
            rel.fare_first = 2.50
        """, rail_stations=rail_stations)
        print("  Dynamically created National Rail relationships")

        # 5. Dynamically Create Transfer Links between Metro and Rail
        # Strictly use INTERCHANGE_TO with travel_time_min to correspond to the algorithmic settings
        # Transfer settings from Metro
        session.run("""
        UNWIND $metro_stations AS m
        WITH m WHERE m.is_interchange_national_rail = true AND m.interchange_national_rail_station_id IS NOT NULL
        MATCH (ms:Station:MetroStation {station_id: m.station_id})
        MATCH (rs:Station:NationalRailStation {station_id: m.interchange_national_rail_station_id})
        MERGE (ms)-[rel1:INTERCHANGE_TO]->(rs)
        SET rel1.travel_time_min = 5,
            rel1.fare = 0.0,
            rel1.fare_standard = 0.0,
            rel1.fare_first = 0.0
        MERGE (rs)-[rel2:INTERCHANGE_TO]->(ms)
        SET rel2.travel_time_min = 5,
            rel2.fare = 0.0,
            rel2.fare_standard = 0.0,
            rel2.fare_first = 0.0
        """, metro_stations=metro_stations)

        # Transfer settings from National Rail (ensure bidirectional correspondence)
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

        # Transfer settings from National Rail (ensure bidirectional correspondence)
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
