from collections import defaultdict, deque
from typing import List, Tuple, Dict, Any, Optional

class FKEdge:
    """
    Represents one FK constraint between parent and child.
    pairs: ordered list of (parent_col, child_col)
    """
    __slots__ = ("parent", "child", "pairs", "constraint_name")

    def __init__(self, parent: str, child: str,
                 pairs: List[Tuple[str, str]],
                 constraint_name: Optional[str] = None):
        self.parent = parent
        self.child = child
        self.pairs = list(pairs)  # ensure list copy
        self.constraint_name = constraint_name

    def conditions(self, left_table_alias: str, right_table_alias: str, direction: str) -> str:
        """
        Render ON conditions in the correct direction.
        direction: "parent->child" or "child->parent"
        """
        if direction == "parent->child":
            terms = [f"`{left_table_alias}`.`{p}` = `{right_table_alias}`.`{c}`" for p, c in self.pairs]
        elif direction == "child->parent":
            terms = [f"`{left_table_alias}`.`{c}` = `{right_table_alias}`.`{p}`" for p, c in self.pairs]
        else:
            raise ValueError("direction must be 'parent->child' or 'child->parent'")
        return " AND ".join(terms)

def _normalize_dependency_row(row: List[Any]) -> FKEdge:
    """
    Accepts rows shaped like:
        [parent_table, child_table, join_info, constraint_name?]
    where join_info can be:
        - list of (parent_col, child_col)  -> preferred (ordered!)
        - dict {parent_col: child_col}     -> acceptable (order not guaranteed)
        - list of dicts [{'parent_col':..., 'child_col':...}] -> also ok
    Returns FKEdge with ordered pairs (best effort if unordered input).
    """
    if len(row) == 3:
        parent, child, join_info = row
        cname = None
    elif len(row) >= 4:
        parent, child, join_info, cname = row[0], row[1], row[2], row[3]
    else:
        raise ValueError("dependency row must have 3 or 4 elements")

    # Normalize join_info to an ordered list of (parent_col, child_col)
    pairs: List[Tuple[str, str]] = []
    if isinstance(join_info, list):
        # Could be list of tuples or list of dicts
        if join_info and isinstance(join_info[0], tuple):
            pairs = list(join_info)
        else:
            # assume list of {'parent_col':..., 'child_col':...}
            for item in join_info:
                pairs.append((item["parent_col"], item["child_col"]))
    elif isinstance(join_info, dict):
        # Dict insertion order (Python 3.7+) might reflect your SQL ORDER BY,
        # but if in doubt prefer passing a list to guarantee order.
        for p, c in join_info.items():
            pairs.append((p, c))
    else:
        raise ValueError("Unsupported join_info type; pass list of tuples or dict")

    return FKEdge(parent=parent, child=child, pairs=pairs, constraint_name=cname)


def build_graph(dependencies: List[List[Any]]):
    """
    Build a graph that keeps multiple FKs between the same tables distinct.
    Returns:
        graph: Dict[str, List[Tuple[str, int, str]]]
               table -> list of (neighbor_table, edge_index, direction)
               direction is from the POV of the current node to neighbor:
                    if node == parent, neighbor == child  => 'parent->child'
                    if node == child,  neighbor == parent => 'child->parent'
        edges: List[FKEdge]
    """
    edges: List[FKEdge] = []
    graph: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)

    for row in dependencies:
        edge = _normalize_dependency_row(row)
        idx = len(edges)
        edges.append(edge)

        # two directional adjacencies, but keep direction label so we can render joins properly
        graph[edge.parent].append((edge.child, idx, "parent->child"))
        graph[edge.child].append((edge.parent, idx, "child->parent"))

    return graph, edges


def bfs_path(graph: Dict[str, List[Tuple[str, int, str]]],
             source: str, target: str):
    """
    BFS to find the shortest path (by number of hops).
    Returns:
        came_from: Dict[str, Tuple[str, int, str]] mapping node -> (prev_node, edge_idx, direction_from_prev_to_node)
        or None if unreachable.
    """
    if source == target:
        return {source: (None, None, None)}

    q = deque([source])
    visited = {source}
    came_from: Dict[str, Tuple[Optional[str], Optional[int], Optional[str]]] = {source: (None, None, None)}

    while q:
        node = q.popleft()
        for neighbor, edge_idx, direction in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                came_from[neighbor] = (node, edge_idx, direction)
                if neighbor == target:
                    return came_from
                q.append(neighbor)

    return None


def reconstruct_path(came_from, source: str, target: str):
    """
    Reconstruct list of (left_table, right_table, edge_idx, direction) in forward order.
    """
    if source == target:
        return []

    chain = []
    cur = target
    while cur != source:
        prev, edge_idx, direction = came_from[cur]
        chain.append((prev, cur, edge_idx, direction))
        cur = prev
    chain.reverse()
    return chain


def build_join_sql(chain, edges: List[FKEdge],
                   table_alias_prefix: str = "t"):
    """
    Builds:
      - ordered list of tables encountered
      - alias map {table_name: alias} in order of appearance
      - SQL join chain text with correct composite-key ON conditions
    Note: If the same table name appears multiple times in the path (rare with BFS),
          aliases are disambiguated by sequence index.
    """
    # Collect ordered tables from chain
    if not chain:
        return [], {}, ""  # source==target; no joins

    ordered_tables = [chain[0][0]]  # start with left table of first hop
    for _, right, _, _ in chain:
        ordered_tables.append(right)

    # Assign deterministic aliases by sequence, even if table names repeat
    alias_map: Dict[Tuple[str, int], str] = {}
    table_occurrence_count: Dict[str, int] = defaultdict(int)
    occurrence_index_for_step: List[int] = []

    # Prepare occurrence index for each table in appearance order
    for t in ordered_tables:
        table_occurrence_count[t] += 1
        occurrence_index_for_step.append(table_occurrence_count[t] - 1)

    # Build alias lookup for each occurrence
    alias_by_occurrence: Dict[Tuple[str, int], str] = {}
    for i, t in enumerate(ordered_tables):
        occ = occurrence_index_for_step[i]
        alias_by_occurrence[(t, occ)] = f"{table_alias_prefix}{i}"

    # Now render join clauses
    parts = []
    # FROM clause with first table + alias
    left_table, left_occ = ordered_tables[0], occurrence_index_for_step[0]
    left_alias = alias_by_occurrence[(left_table, left_occ)]
    parts.append(f" `{left_table}` ")

    for i, (l_tbl, r_tbl, edge_idx, direction) in enumerate(chain, start=1):
        # map occurrences
        l_occ = occurrence_index_for_step[i - 1]
        r_occ = occurrence_index_for_step[i]
        l_alias = alias_by_occurrence[(l_tbl, l_occ)]
        r_alias = alias_by_occurrence[(r_tbl, r_occ)]

        edge = edges[edge_idx]
        on_expr = edge.conditions(left_table_alias=r_tbl,
                                  right_table_alias=l_tbl,
                                  direction=direction)
        parts.append(f"LEFT JOIN {r_tbl} ON {on_expr}")

    join_sql = "\n".join(parts)
    # Provide a simpler alias map keyed by table appearance order
    appearance_aliases = {ordered_tables[i]: alias_by_occurrence[(ordered_tables[i], occurrence_index_for_step[i])]
                          for i in range(len(ordered_tables))}
    return ordered_tables, appearance_aliases, join_sql


def find_join_route_with_composites(dependencies: List[List[Any]],
                                    source_table: str,
                                    target_table: str):
    """
    High-level function:
        - builds graph (with multiple edges retained)
        - BFS path
        - constructs join chain SQL preserving composite-key order
    """
    graph, edges = build_graph(dependencies)
    came_from = bfs_path(graph, source_table, target_table)
    if not came_from:
        return None

    chain = reconstruct_path(came_from, source_table, target_table)
    ordered_tables, aliases, join_sql = build_join_sql(chain, edges)
    return {
        "tables_in_path": ordered_tables,
        "aliases": aliases,
        "join_chain_sql": join_sql,
        "edges_used": chain,  # includes edge indices and directions
    }


def find_join_route_for_multiple_target_tables_with_composites(
    dependencies: List[List[Any]],
    source_table: str,
    target_tables: List[str]
):
    """
    Given a source table and a list of target tables, compute the minimal join
    chain that covers all target tables. Uses the existing BFS-based routing
    with composite key preservation.

    Returns:
        {
            "tables_in_path": [...],
            "aliases": {...},
            "join_chain_sql": "...",
            "edges_used": [...],        # combined edges
            "per_target_paths": {...},  # diagnostic / debugging info
        }
    """

    # Step 1: Build graph & edges once
    graph, edges = build_graph(dependencies)

    all_edges_used = []
    all_tables = [source_table]  # will deduplicate later
    per_target_paths = {}

    # Step 2: BFS for each target independently
    for tgt in target_tables:
        came_from = bfs_path(graph, source_table, tgt)
        if not came_from:

            return None

            #raise ValueError(f"No join path from {source_table} to {tgt}")

        chain = reconstruct_path(came_from, source_table, tgt)

        # store for debugging or introspection
        per_target_paths[tgt] = chain

        # accumulate edges and tables
        all_edges_used.extend(chain)
        if chain:
            all_tables.extend([hop[1] for hop in chain])

    # Step 3: Deduplicate edges in forward order
    seen = set()
    merged_chain = []
    for hop in all_edges_used:
        if hop not in seen:
            merged_chain.append(hop)
            seen.add(hop)

    # Step 4: Re-run the SQL join builder on merged chain
    tables_in_path, aliases, join_chain_sql = build_join_sql(merged_chain, edges)

    return {
        "tables_in_path": tables_in_path,
        "aliases": aliases,
        "join_chain_sql": join_chain_sql,
        "edges_used": merged_chain,
        "per_target_paths": per_target_paths,
    }