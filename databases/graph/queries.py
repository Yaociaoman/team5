"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).
    """
    default_response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": None,
        "path": [],
        "legs": []
    }

    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"

    cypher = f"""
        MATCH (origin:{label} {{station_id: $origin_id}})
        MATCH (dest:{label}   {{station_id: $dest_id}})
        CALL apoc.algo.dijkstra(origin, dest, '{rel_type}', 'travel_time_min')
        YIELD path, weight
        RETURN path, weight
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher, origin_id=origin_id, dest_id=destination_id)
            record = result.single()

            if not record:
                return default_response

            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            legs = [
                {
                    "from":     nodes[i]["station_id"],
                    "to":       nodes[i + 1]["station_id"],
                    "line":     r.get("line", ""),
                    "time_min": r.get("travel_time_min", 0),
                }
                for i, r in enumerate(rels)
            ]

            return {
                "found":          True,
                "origin_id":      origin_id,
                "destination_id": destination_id,
                "total_time_min": record["weight"],
                "path":           stations,
                "legs":           legs,
            }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.
    """
    default_response = {
        "found": False,
        "total_fare_usd": None,
        "stations": [],
        "legs": []
    }

    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"

    fare_prop = "fare_standard" if fare_class == "standard" else "fare_first"

    cypher = f"""
        MATCH (origin:{label} {{station_id: $origin_id}})
        MATCH (dest:{label}   {{station_id: $dest_id}})
        CALL apoc.algo.dijkstra(origin, dest, '{rel_type}', '{fare_prop}')
        YIELD path, weight
        RETURN path, weight
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher, origin_id=origin_id, dest_id=destination_id)
            record = result.single()

            if not record:
                return default_response

            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            legs = [
                {
                    "from":     nodes[i]["station_id"],
                    "to":       nodes[i + 1]["station_id"],
                    "line":     r.get("line", ""),
                    "fare_usd": float(r.get(fare_prop, 0.0)),
                }
                for i, r in enumerate(rels)
            ]

            return {
                "found":          True,
                "total_fare_usd": round(record["weight"], 2),
                "stations":       stations,
                "legs":           legs,
            }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
    fare_class: str = "standard",
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    """
    if origin_id == avoid_station_id or destination_id == avoid_station_id:
        return []

    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"
        
    fare_prop = "fare_standard" if fare_class == "standard" else "fare_first"

    cypher = f"""
        MATCH (origin:{label} {{station_id: $origin_id}})
        MATCH (dest:{label}   {{station_id: $dest_id}})
        MATCH path = (origin)-[:{rel_type}*1..15]->(dest)
        WHERE NONE(n IN nodes(path) WHERE n.station_id = $avoid_id
                   AND n.station_id <> $origin_id
                   AND n.station_id <> $dest_id)
        RETURN path
        ORDER BY length(path)
        LIMIT $limit
    """

    routes = []
    with _driver() as driver:
        with driver.session() as session:
            results = session.run(
                cypher,
                origin_id=origin_id,
                dest_id=destination_id,
                avoid_id=avoid_station_id,
                limit=max_routes,
            )

            for record in results:
                path  = record["path"]
                nodes = list(path.nodes)
                rels  = list(path.relationships)
                legs = [
                    {
                        "from":     nodes[i]["station_id"],
                        "to":       nodes[i + 1]["station_id"],
                        "line":     r.get("line", ""),
                        "time_min": r.get("travel_time_min", 0),
                        "fare_usd": float(r.get(fare_prop, 0.0)),
                    }
                    for i, r in enumerate(rels)
                ]
                routes.append(legs)

    return routes


# ── CROSS-NETWORK INTERCHANGE_TO PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.
    """
    default_response = {
        "found": False,
        "stations": [],
        "interchange_points": [],
        "total_time_min": None
    }

    origin_label = "MetroStation" if origin_id.startswith("MS") else "RailStation"
    dest_label   = "MetroStation" if destination_id.startswith("MS") else "RailStation"

    # 已修正：將 $destination_id 對齊成下方傳入的 $dest_id
    cypher = f"""
        MATCH (origin:{origin_label} {{station_id: $origin_id}})
        MATCH (dest:{dest_label}     {{station_id: $dest_id}})
        MATCH path = shortestPath(
            (origin)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*]-(dest)
        )
        RETURN path,
               reduce(t = 0, r IN relationships(path) |
                   t + coalesce(r.travel_time_min, r.walk_time_min, 0)
               ) AS total_time
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher, origin_id=origin_id, dest_id=destination_id)
            record = result.single()

            if not record:
                return default_response

            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            interchange_points = []
            for i, r in enumerate(rels):
                if r.type == "INTERCHANGE_TO":
                    walk_time = r.get("walk_time_min", r.get("travel_time_min", 5))
                    interchange_points.append({
                        "from_station":  nodes[i]["station_id"],
                        "to_station":    nodes[i + 1]["station_id"],
                        "walk_time_min": walk_time,
                    })

            return {
                "found":              True,
                "stations":           stations,
                "interchange_points": interchange_points,
                "total_time_min":     record["total_time"],
            }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    """
    if hops < 0:
        return []

    cypher = f"""
        MATCH (source)
        WHERE (source:MetroStation OR source:RailStation)
          AND source.station_id = $station_id
        MATCH (source)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..{hops}]-(neighbor)
        WHERE neighbor.station_id <> $station_id
        WITH neighbor,
             min(length(shortestPath(
                 (source)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*]->(neighbor)
             ))) AS hops_away
        RETURN DISTINCT
               neighbor.station_id AS station_id,
               neighbor.name       AS name,
               hops_away,
               neighbor.lines      AS lines_affected
        ORDER BY hops_away, station_id
    """

    with _driver() as driver:
        with driver.session() as session:
            results = session.run(cypher, station_id=delayed_station_id)

            return [
                {
                    "station_id":     r["station_id"],
                    "name":           r["name"],
                    "hops_away":      r["hops_away"],
                    "lines_affected": r["lines_affected"] or [],
                }
                for r in results
            ]


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.
    """
    cypher = """
        MATCH (s)-[r:METRO_LINK|RAIL_LINK]->(neighbor)
        WHERE s.station_id = $station_id
        RETURN neighbor.station_id AS station_id,
               neighbor.name       AS name,
               r.line              AS line,
               r.travel_time_min   AS travel_time_min,
               r.fare_standard     AS fare_usd
        ORDER BY neighbor.station_id
    """

    with _driver() as driver:
        with driver.session() as session:
            results = session.run(cypher, station_id=station_id)

            return [
                {
                    "station_id":      r["station_id"],
                    "name":            r["name"],
                    "line":            r["line"],
                    "travel_time_min": r["travel_time_min"],
                    "fare_usd":        r["fare_usd"],
                }
                for r in results
            ]