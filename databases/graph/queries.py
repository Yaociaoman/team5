"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    # Default response returned when no path is found
    default_response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": None,
        "path": [],
        "legs": []
    }

    # 1. Infer network from station ID prefix if set to "auto"
    #    MS prefix → metro network, NR prefix → national rail network
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    # 2. Select the correct node label and relationship type based on network
    #    MetroStation nodes are linked by METRO_LINK relationships
    #    RailStation nodes are linked by RAIL_LINK relationships
    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"

    # 3. Build the Cypher query using APOC Dijkstra algorithm
    #    - Match origin and destination nodes by station_id property
    #    - Call apoc.algo.dijkstra with travel_time_min as the edge weight
    #    - YIELD path and weight (total accumulated cost)
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

            # Return default response if APOC finds no reachable path
            if not record:
                return default_response

            # 4. Unpack nodes and relationships from the returned path object
            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            # 5. Build the ordered list of stations along the route
            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            # 6. Build the list of individual legs (one per relationship)
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

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    # Default response returned when no path is found
    default_response = {
        "found": False,
        "total_fare_usd": None,
        "stations": [],
        "legs": []
    }

    # 1. Infer network from station ID prefix if set to "auto"
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    # 2. Select the correct node label and relationship type based on network
    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"

    # 3. Build the Cypher query using APOC Dijkstra algorithm
    #    - Both METRO_LINK and RAIL_LINK relationships store fare_standard and fare_first
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

            # Return default response if no path exists between the two stations
            if not record:
                return default_response

            # 4. Unpack nodes and relationships from the returned path object
            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            # 5. Build the ordered list of stations along the cheapest route
            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            # 6. Build the list of individual legs with per-leg fare information
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
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return
        fare_class:        "standard" or "first" (national rail only)

    Returns:
        List of routes, each route is a list of leg dicts
    """
    # Guard: if the avoided station is the origin or destination, no valid route exists
    if origin_id == avoid_station_id or destination_id == avoid_station_id:
        return []

    # 1. Infer network from station ID prefix if set to "auto"
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"

    # 2. Select the correct node label and relationship type based on network
    if network == "metro":
        label, rel_type = "MetroStation", "METRO_LINK"
    else:
        label, rel_type = "RailStation", "RAIL_LINK"
        
    fare_prop = "fare_standard" if fare_class == "standard" else "fare_first"

    # 3. Build the Cypher query using variable-length paths
    #    - NONE(...) clause filters out any path that passes through the avoided station
    #    - The avoided station is allowed to be the origin or destination (edge case guard)
    #    - ORDER BY length(path) to return the shortest available alternative routes
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

            # 4. Parse each returned path into a list of leg dicts
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

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    # Default response returned when no cross-network path is found
    default_response = {
        "found": False,
        "stations": [],
        "interchange_points": [],
        "total_time_min": None
    }

    # 1. Select the correct node label for origin and destination
    #    based on station ID prefix (MS = metro, NR = national rail)
    origin_label = "MetroStation" if origin_id.startswith("MS") else "RailStation"
    dest_label   = "MetroStation" if destination_id.startswith("MS") else "RailStation"

    # 2. Build the Cypher query using shortestPath
    #    - Allows traversal across METRO_LINK, RAIL_LINK, and INTERCHANGE_TO relationships
    #    - reduce() accumulates total travel time across all relationships in the path
    #    - coalesce() handles INTERCHANGE_TO relationships which use walk_time_min instead
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

            # Return default response if no cross-network path could be found
            if not record:
                return default_response

            # 3. Unpack nodes and relationships from the returned path object
            path  = record["path"]
            nodes = list(path.nodes)
            rels  = list(path.relationships)

            # 4. Build the ordered list of all stations along the route
            stations = [
                {"station_id": n["station_id"], "name": n["name"]}
                for n in nodes
            ]

            # 5. Identify interchange points — relationships of type INTERCHANGE_TO
            #    These represent the physical walk between metro and rail platforms
            interchange_points = []
            for i, r in enumerate(rels):
                if r.type == "INTERCHANGE_TO":
                    # Check both walk_time_min and travel_time_min as fallback
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
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    # Guard: negative hops value is not meaningful
    if hops < 0:
        return []

    # 1. Build the Cypher query using variable-length relationship matching
    #    - Searches up to `hops` steps away from the disrupted station
    #    - Works across both MetroStation and RailStation node labels
    #    - min() aggregation picks the shortest hop distance for each neighbor
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

            # 2. Parse each record into the required output format
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

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    # 1. Build the Cypher query to find all directly adjacent stations
    #    - Matches both METRO_LINK and RAIL_LINK outgoing relationships
    #    - Returns the neighboring station's ID, name, line, time, and fare
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

            # 2. Parse each record into the required output format
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