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
    # 預設初始化回傳字典格式（未找到路徑時的預設值）
    default_response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": 0.0,
        "path": [],
        "legs": []
    }

    # 1. 解析與判斷 Network 邏輯，決定 APOC 要動態匹配的關係類型 (Relationship Types)
    # 根據規格要求：metro 走 METRO_LINK，rail 走 RAIL_LINK，跨網走 INTERCHANGE_TO
    if network == "metro":
        rel_filter = "METRO_LINK"
    elif network == "rail":
        rel_filter = "RAIL_LINK"
    elif network == "auto":
        # 判斷起終點的網路屬性 (MS = Metro, NR = Rail)
        origin_type = "metro" if origin_id.startswith("MS") else "rail"
        dest_type = "metro" if destination_id.startswith("MS") else "rail"
        
        if origin_type != dest_type:
            # 跨網路搜尋：允許走 Metro、Rail 路線以及轉乘通道
            rel_filter = "METRO_LINK|RAIL_LINK|INTERCHANGE_TO"
        else:
            # 同網路搜尋
            rel_filter = "METRO_LINK" if origin_type == "metro" else "RAIL_LINK"
    else:
        # 防禦性程式碼，若傳入不支援的 network 參數則直接返回未找到
        return default_response

    # 2. 撰寫 Cypher 查詢語句
    # 步驟 A: 根據 ID 找到起點與終點節點
    # 步驟 B: 呼叫 apoc.algo.dijkstra 計算最短路徑與權重
    # 步驟 C: 將路徑中的節點 (nodes) 與關係 (relationships) 解構出來方便 Python 處理
    cypher_query = """
    MATCH (start:Station {station_id: $origin_id})
    MATCH (end:Station {station_id: $destination_id})
    
    CALL apoc.algo.dijkstra(start, end, $rel_filter, 'travel_time_min') 
    YIELD path, weight
    
    RETURN 
        weight AS total_time,
        [n IN nodes(path) | {station_id: n.station_id, name: n.name}] AS station_path,
        [r IN relationships(path) | {
            line: coalesce(r.line, "Interchange"), 
            from_id: startNode(r).station_id, 
            to_id: endNode(r).station_id, 
            duration: r.travel_time_min
        }] AS route_legs
    """

    # 3. 建立資料庫連線並執行
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query, 
                origin_id=origin_id, 
                destination_id=destination_id, 
                rel_filter=rel_filter
            )
            
            record = result.single()
            
            # 若 APOC 沒有找到任何路徑，record 會是 None
            if not record:
                return default_response
            
            # 4. 封裝符合合約要求的格式
            return {
                "found": True,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "total_time_min": record["total_time"],
                "path": record["station_path"],
                "legs": record["route_legs"]
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
    # 預設未找到路徑時的回傳格式
    default_response = {
        "found": False,
        "total_fare_usd": 0.0,
        "stations": [],
        "legs": []
    }

    # 1. 判斷網路類型 (Network Filter)
    if network == "metro":
        rel_filter = "METRO_LINK"
        weight_property = "fare"  # 捷運固定使用 fare
    elif network == "rail":
        rel_filter = "RAIL_LINK"
        # 國鐵根據艙等選擇對應的票價屬性
        weight_property = "fare_first" if fare_class == "first" else "fare_standard"
    elif network == "auto":
        # 自動根據起終點 ID 前綴判斷 (MS = Metro, NR = Rail)
        origin_type = "metro" if origin_id.startswith("MS") else "rail"
        dest_type = "metro" if destination_id.startswith("MS") else "rail"
        
        if origin_type != dest_type:
            # 跨網路：允許地鐵、國鐵與轉乘
            rel_filter = "METRO_LINK|RAIL_LINK|INTERCHANGE_TO"
            # 跨網時演算法內部需要權重屬性名稱一致。
            # 如果 Neo4j 中不同關係的票價屬性名稱不同，我們在 Cypher 中需使用通用的屬性，
            # 或者是確保你的資料庫中，INTERCHANGE_TO 的轉乘票價（通常為 0）同時存在於對應的屬性中。
            # 這裡我們依據起點或艙等動態指定主權重欄位。
            weight_property = "fare_first" if fare_class == "first" and origin_type == "rail" else "fare_standard"
        else:
            if origin_type == "metro":
                rel_filter = "METRO_LINK"
                weight_property = "fare"
            else:
                rel_filter = "RAIL_LINK"
                weight_property = "fare_first" if fare_class == "first" else "fare_standard"
    else:
        return default_response

    # 2. 撰寫 Cypher 查詢語句
    # 由於不同關係（如 METRO_LINK 的 fare 與 RAIL_LINK 的 fare_standard）屬性名稱可能相異，
    # 為了讓 APOC Dijkstra 能正確在跨網路或不同路網運行，
    # 我們在 APOC 執行時動態傳入指定的 $weight_property。
    cypher_query = """
    MATCH (start:Station {station_id: $origin_id})
    MATCH (end:Station {station_id: $destination_id})
    
    // 呼叫 APOC Dijkstra 演算法，傳入動態的關係過濾器與權重屬性
    CALL apoc.algo.dijkstra(start, end, $rel_filter, $weight_property, 0.0) 
    YIELD path, weight
    
    RETURN 
        weight AS total_fare,
        [n IN nodes(path) | n.station_id] AS station_ids,
        [r IN relationships(path) | {
            line: coalesce(r.line, "Interchange"),
            from_id: startNode(r).station_id,
            to_id: endNode(r).station_id,
            // 動態從關係中取得對應的票價，若無該屬性（如轉乘通道）則預設為 0.0
            fare: coalesce(r[$weight_property], r["fare"], 0.0)
        }] AS route_legs
    """

    # 3. 建立 Session 並執行查詢
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
                rel_filter=rel_filter,
                weight_property=weight_property
            )
            
            record = result.single()
            
            # 檢查是否順利找到最短（最便宜）路徑
            if not record:
                return default_response
            
            # 4. 封裝符合合約要求的格式回傳
            return {
                "found": True,
                "total_fare_usd": float(record["total_fare"]),
                "stations": record["station_ids"],
                "legs": record["route_legs"]
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
    # 如果起點或終點本身就是要避開的車站，直接回傳空列表（防禦性防錯）
    if origin_id == avoid_station_id or destination_id == avoid_station_id:
        return []

    # 1. 解析與判斷 Network 邏輯，決定 APOC 走訪時允許通過的關係類型 (Relationship Filter)
    if network == "metro":
        rel_filter = "METRO_LINK"
    elif network == "rail":
        rel_filter = "RAIL_LINK"
    elif network == "auto":
        origin_type = "metro" if origin_id.startswith("MS") else "rail"
        dest_type = "metro" if destination_id.startswith("MS") else "rail"
        
        if origin_type != dest_type:
            # 跨網路搜尋：允許走地鐵、國鐵與轉乘通道（後方加上 > 代表方向性，APOC 慣用法）
            rel_filter = "METRO_LINK>|RAIL_LINK>|INTERCHANGE_TO>"
        else:
            rel_filter = "METRO_LINK>" if origin_type == "metro" else "RAIL_LINK>"
    else:
        return []

    # 2. 撰寫 Cypher 查詢語句
    # 步驟 A: 匹配起點、終點、以及要避開（黑名單）的車站節點
    # 步驟 B: 使用 apoc.path.expandConfig 進行廣度優先/深度優先走訪
    #         - terminatorNodes: [end] 代表走到終點就停，不繼續往下搜
    #         - blacklistNodes: [avoid] 在走訪底層直接屏蔽該節點，圖形擴展時絕對不踏入
    #         - relationshipFilter: 限制只能走特定路網的邊
    #         - limit: 限制回傳的最長路徑條數 (max_routes)
    cypher_query = """
    MATCH (start:Station {station_id: $origin_id})
    MATCH (end:Station {station_id: $destination_id})
    MATCH (avoid:Station {station_id: $avoid_station_id})
    
    CALL apoc.path.expandConfig(start, {
        terminatorNodes: [end],
        blacklistNodes: [avoid],
        relationshipFilter: $rel_filter,
        limit: $max_routes,
        uniqueness: "NODE_PATH"
    })
    YIELD path
    
    // 將找到的每條 path 解構成多個關係 (relationships) 的列表
    RETURN [r IN relationships(path) | {
        from_id: startNode(r).station_id,
        to_id: endNode(r).station_id,
        line: coalesce(r.line, "Interchange"),
        travel_time_min: r.travel_time_min
    }] AS alternative_route
    """

    routes = []

    # 3. 建立 Session 連線並執行查詢
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id,
                avoid_station_id=avoid_station_id,
                rel_filter=rel_filter,
                max_routes=max_routes
            )
            
            # 4. 解析結果
            for record in result:
                # record["alternative_route"] 本身就是一個 list[dict] (代表單一條路線的所有路段)
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
    # 預設未找到路徑時的回傳格式
    default_response = {
        "found": False,
        "stations": [],
        "interchange_points": [],
        "total_time_min": 0.0
    }

    # 1. 撰寫 Cypher 查詢語句
    # 步驟 A: 補上 :Station 標籤以觸發 Unique Constraint 索引
    # 步驟 B: 使用 f-string 將關係過濾器 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO' 拼入 APOC Dijkstra 中
    # 步驟 C: 利用列表推導式與 DISTINCT 機制，撈出所有類型為 INTERCHANGE_TO 的轉乘車站 ID
    cypher_query = f"""
    MATCH (start:Station {{station_id: $origin_id}})
    MATCH (end:Station {{station_id: $destination_id}})
    
    CALL apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 'travel_time_min') 
    YIELD path, weight
    
    // 找出路徑中所有屬於轉乘邊的起迄點站 ID
    WITH path, weight,
         [r IN relationships(path) WHERE type(r) = 'INTERCHANGE_TO' | startNode(r).station_id] +
         [r IN relationships(path) WHERE type(r) = 'INTERCHANGE_TO' | endNode(r).station_id] AS interchange_list
         
    // 使用 apoc.coll.toSet 將收集到的轉乘站 ID 進行去重複處理
    RETURN 
        weight AS total_time,
        [n IN nodes(path) | n.station_id] AS station_ids,
        apoc.coll.toSet(interchange_list) AS unique_interchanges
    """

    # 2. 建立 Session 連線並執行查詢
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                origin_id=origin_id,
                destination_id=destination_id
            )
            
            record = result.single()
            
            # 檢查是否順利找到最快跨網轉乘路徑
            if not record:
                return default_response
            
            # 3. 封裝符合合約要求的格式回傳
            return {
                "found": True,
                "stations": record["station_ids"],
                "interchange_points": record["unique_interchanges"],
                "total_time_min": float(record["total_time"])
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
    if hops < 0:
        return []

    # 處理邊界條件：hops=0 時，只回傳該故障車站本身
    if hops == 0:
        cypher_query = """
        MATCH (s:Station {station_id: $delayed_station_id})
        RETURN s.station_id AS station_id, s.name AS name
        """
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(cypher_query, delayed_station_id=delayed_station_id)
                record = result.single()
                if record:
                    return [{
                        "station_id": record["station_id"],
                        "name": record["name"],
                        "hops_away": 0,
                        "lines_affected": []
                    }]
                return []

    # 1. 撰寫 Cypher 查詢語句
    # 步驟 A: 補上 :Station 標籤以觸發 Unique Constraint 索引
    # 步驟 B: 使用 f-string 安全拼入最大步數限制 (1..{hops})，匹配 CONNECTED_TO 與 INTERCHANGE_TO
    # 步驟 C: 利用 length(path) 取得距離，並用列表推導式收集受影響線路
    # 步驟 D: 透過 GROUP BY (聚合) 與 apoc.coll.toSet 進行去重複，最後依 hops_away 排序
    cypher_query = f"""
    MATCH path = (start:Station {{station_id: $delayed_station_id}})-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..{hops}]->(affected:Station)
    
    // 排除起點本身（雖然 *1.. 預設就不會包含 0 步，但這可作為防禦性過濾）
    WHERE affected.station_id <> $delayed_station_id
    
    // 對每條路徑提取所有關係的線路名稱
    WITH affected, 
         length(path) AS distance,
         [r IN relationships(path) | coalesce(r.line, "Interchange")] AS lines_in_path
         
    // 按照受影響車站進行聚合，計算最小步數 (最短波及距離)，並將所有路徑的線路合併去重複
    RETURN 
        affected.station_id AS station_id,
        affected.name AS name,
        min(distance) AS hops_away,
        apoc.coll.toSet(apoc.coll.flatten(collect(lines_in_path))) AS lines_affected
    ORDER BY hops_away ASC, station_id ASC
    """

    ripple_effect = []

    # 2. 建立 Session 連線並執行查詢
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query,
                delayed_station_id=delayed_station_id
            )
            
            # 3. 解析結果並整理成要求的 list[dict] 格式
            for record in result:
                ripple_effect.append({
                    "station_id": record["station_id"],
                    "name": record["name"],
                    "hops_away": int(record["hops_away"]),
                    "lines_affected": record["lines_affected"]
                })
                
    return ripple_effect


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    # 1. 使用模組內定義的 _driver() 獲取 driver 實例
    with _driver() as driver:
        # 2. 開啟一個資料庫會話 (Session)
        with driver.session() as session:
            # 3. 定義 Cypher 查詢語法
            # 透過起點的 station_id 找到相鄰的下一個車站 next_station
            cypher_query = """
            MATCH (start:Station {station_id: $station_id})-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]->(next_station:Station)
            RETURN 
                next_station.station_id AS next_id,
                next_station.name AS next_name,
                r.line AS line,
                r.travel_time_min AS travel_time_min
            """
            
            # 4. 執行查詢並帶入參數
            result = session.run(cypher_query, station_id=station_id)
            
            # 5. 解析結果並整理成要求的 list[dict] 格式
            connections = []
            for record in result:
                connections.append({
                    "station_id": record["next_id"],
                    "name": record["next_name"],
                    "line": record["line"],
                    "travel_time_min": record["travel_time_min"]
                })
                
            return connections
