"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1-M4 + national rail NR1-NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro -> rail or rail -> metro)
  - Show delay ripple: which stations are affected within N hops

Graph Schema (must match seed_neo4j.py):
  Node labels  : MetroStation           {station_id, name}
                 NationalRailStation    {station_id, name}
  Relationships: METRO_LINK             {line, travel_time_min, fare}
                 RAIL_LINK              {line, travel_time_min, fare_standard, fare_first}
                 INTERCHANGE_TO         {travel_time_min}  (transfer between networks, fare = 0)

Note: MATCH clauses use no label so both MetroStation and NationalRailStation
are matched.  Node label constraints are defined in databases/graph/seed.cypher.
"""

from __future__ import annotations

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


# ── Helper ────────────────────────────────────────────────────────────────────

def _resolve_rel_filter(network: str, origin_id: str, destination_id: str) -> str | None:
    """
    Return the APOC relationship filter string for the given network argument.

    Station ID convention: "MS" prefix = MetroStation, "NR" prefix = NationalRailStation.
    Returns None when the network value is unrecognised.
    """
    if network == "metro":
        return "METRO_LINK"
    if network == "rail":
        return "RAIL_LINK"
    if network == "auto":
        origin_is_metro = origin_id.upper().startswith("MS")
        dest_is_metro = destination_id.upper().startswith("MS")
        if origin_is_metro and dest_is_metro:
            return "METRO_LINK"
        if not origin_is_metro and not dest_is_metro:
            return "RAIL_LINK"
        # Cross-network: allow all relationship types
        return "METRO_LINK|RAIL_LINK|INTERCHANGE_TO"
    return None


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
    default_response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": 0.0,
        "path": [],
        "legs": [],
    }

    rel_filter = _resolve_rel_filter(network, origin_id, destination_id)
    if rel_filter is None:
        return default_response

    # No node label in MATCH so both MetroStation and NationalRailStation are matched.
    # coalesce(r.line, 'Interchange') handles INTERCHANGE_TO edges that carry no line name.
    cypher_query = """
    MATCH (start {station_id: $origin_id})
    MATCH (end   {station_id: $destination_id})

    CALL apoc.algo.dijkstra(start, end, $rel_filter, 'travel_time_min')
    YIELD path, weight

    RETURN
        weight AS total_time,
        [n IN nodes(path) | {station_id: n.station_id, name: n.name}] AS station_path,
        [r IN relationships(path) | {
            line:            coalesce(r.line, 'Interchange'),
            from_id:         startNode(r).station_id,
            to_id:           endNode(r).station_id,
            travel_time_min: r.travel_time_min
        }] AS route_legs
    LIMIT 1
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
                rel_filter=rel_filter,
            )
            record = result.single()

            if not record:
                return default_response

            return {
                "found": True,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "total_time_min": float(record["total_time"]),
                "path": record["station_path"],
                "legs": record["route_legs"],
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
    default_response = {
        "found": False,
        "total_fare_usd": 0.0,
        "stations": [],
        "legs": [],
    }

    rel_filter = _resolve_rel_filter(network, origin_id, destination_id)
    if rel_filter is None:
        return default_response

    # Determine which fare property to use as the Dijkstra weight.
    # Metro edges store a single "fare" property.
    # Rail edges store "fare_standard" and "fare_first".
    # INTERCHANGE_TO edges carry no fare; APOC defaults missing weights to 0.0
    # (the fifth argument to apoc.algo.dijkstra).
    if "METRO_LINK" in rel_filter and "RAIL_LINK" not in rel_filter:
        weight_prop = "fare"
    else:
        weight_prop = "fare_first" if fare_class == "first" else "fare_standard"

    cypher_query = """
    MATCH (start {station_id: $origin_id})
    MATCH (end   {station_id: $destination_id})

    CALL apoc.algo.dijkstra(start, end, $rel_filter, $weight_prop, 0.0)
    YIELD path, weight

    RETURN
        weight AS total_fare,
        [n IN nodes(path) | n.station_id] AS station_ids,
        [r IN relationships(path) | {
            line:    coalesce(r.line, 'Interchange'),
            from_id: startNode(r).station_id,
            to_id:   endNode(r).station_id,
            fare:    coalesce(r[$weight_prop], r.fare, 0.0)
        }] AS route_legs
    LIMIT 1
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
                rel_filter=rel_filter,
                weight_prop=weight_prop,
            )
            record = result.single()

            if not record:
                return default_response

            return {
                "found": True,
                "total_fare_usd": float(record["total_fare"]),
                "stations": record["station_ids"],
                "legs": record["route_legs"],
            }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
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

    Returns:
        List of routes, each route is a list of leg dicts
    """
    # Guard: if origin or destination is the avoided station, no route is possible
    if origin_id == avoid_station_id or destination_id == avoid_station_id:
        return []

    rel_filter = _resolve_rel_filter(network, origin_id, destination_id)
    if rel_filter is None:
        return []

    # Add ">" suffix to each relationship type to enforce direction in expandConfig.
    directed_filter = "|".join(t + ">" for t in rel_filter.split("|"))

    # apoc.path.expandConfig with blacklistNodes excludes the avoided station
    # at the graph traversal level — it never appears in any returned path.
    # uniqueness: NODE_PATH ensures no station is visited twice within one route.
    cypher_query = """
    MATCH (start {station_id: $origin_id})
    MATCH (end   {station_id: $destination_id})
    MATCH (avoid {station_id: $avoid_station_id})

    CALL apoc.path.expandConfig(start, {
        terminatorNodes:    [end],
        blacklistNodes:     [avoid],
        relationshipFilter: $directed_filter,
        limit:              $max_routes,
        uniqueness:         'NODE_PATH'
    })
    YIELD path

    RETURN [r IN relationships(path) | {
        from_id:         startNode(r).station_id,
        to_id:           endNode(r).station_id,
        line:            coalesce(r.line, 'Interchange'),
        travel_time_min: r.travel_time_min
    }] AS alternative_route
    """

    routes = []
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
                avoid_station_id=avoid_station_id,
                directed_filter=directed_filter,
                max_routes=max_routes,
            )
            for record in result:
                routes.append(record["alternative_route"])

    return routes


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

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
    default_response = {
        "found": False,
        "stations": [],
        "interchange_points": [],
        "total_time_min": 0.0,
    }

    # All three relationship types must be traversable for cross-network routing.
    # apoc.coll.toSet deduplicates interchange station IDs collected by concatenating
    # the start and end node of every INTERCHANGE_TO edge in the path.
    cypher_query = """
    MATCH (start {station_id: $origin_id})
    MATCH (end   {station_id: $destination_id})

    CALL apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 'travel_time_min')
    YIELD path, weight

    WITH path, weight,
         [r IN relationships(path) WHERE type(r) = 'INTERCHANGE_TO' | startNode(r).station_id] +
         [r IN relationships(path) WHERE type(r) = 'INTERCHANGE_TO' | endNode(r).station_id]
         AS interchange_list

    RETURN
        weight                                AS total_time,
        [n IN nodes(path) | n.station_id]     AS station_ids,
        apoc.coll.toSet(interchange_list)      AS unique_interchanges
    LIMIT 1
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
            )
            record = result.single()

            if not record:
                return default_response

            return {
                "found": True,
                "stations": record["station_ids"],
                "interchange_points": record["unique_interchanges"],
                "total_time_min": float(record["total_time"]),
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
    if hops < 1:
        return []

    # Variable-length pattern *1..{hops} expands outward up to N hops.
    # INTERCHANGE_TO is included so cross-network ripple is captured when
    # the disrupted station sits at a network boundary.
    # apoc.coll.flatten collapses the nested list from collect(lines_in_path)
    # before deduplication with apoc.coll.toSet.
    cypher_query = f"""
    MATCH path = (start {{station_id: $delayed_station_id}})
                 -[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..{hops}]->
                 (affected)
    WHERE affected.station_id <> $delayed_station_id

    WITH affected,
         length(path) AS distance,
         [r IN relationships(path) | coalesce(r.line, 'Interchange')] AS lines_in_path

    RETURN
        affected.station_id                                         AS station_id,
        affected.name                                               AS name,
        min(distance)                                               AS hops_away,
        apoc.coll.toSet(apoc.coll.flatten(collect(lines_in_path)))  AS lines_affected
    ORDER BY hops_away ASC, station_id ASC
    """

    ripple_effect = []
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                delayed_station_id=delayed_station_id,
            )
            for record in result:
                ripple_effect.append({
                    "station_id":    record["station_id"],
                    "name":          record["name"],
                    "hops_away":     int(record["hops_away"]),
                    "lines_affected": record["lines_affected"],
                })

    return ripple_effect


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    # Both METRO_LINK and RAIL_LINK are checked so the function works for any
    # station regardless of network. INTERCHANGE_TO is included so transfer
    # options appear alongside regular service connections.
    cypher_query = """
    MATCH (start {station_id: $station_id})-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]->(next)
    RETURN
        next.station_id                 AS next_id,
        next.name                       AS next_name,
        type(r)                         AS rel_type,
        coalesce(r.line, 'Interchange') AS line,
        r.travel_time_min               AS travel_time_min
    ORDER BY line, next_id
    """

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, station_id=station_id)
            return [
                {
                    "station_id":      record["next_id"],
                    "name":            record["next_name"],
                    "rel_type":        record["rel_type"],
                    "line":            record["line"],
                    "travel_time_min": record["travel_time_min"],
                }
                for record in result
            ]