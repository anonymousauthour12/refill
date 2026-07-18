
from decimal import Decimal
from datetime import date, datetime
from itertools import combinations
from typing import List, Tuple, Any, Optional, Dict

Row = Tuple[Any, ...]  # arbitrary-length tuples


def select_diverse_points(
    rows: List[Row],
    x_threshold: Any,
    X: int = 3,
    headers: Optional[List[str]] = None,
    children_weight: float = 1.0,
    siblings_weight: float = 1.0,
) -> List[Row]:
    """
    Diversity-first selection of up to X rows (default=3) from `rows` such that:
      - Sum(estimated_size) <= x_threshold
      - Diversity of target_column is prioritized:
          * booleans: include both True and False when possible
          * strings: prefer distinct labels
          * numeric/date-like: maximize spread (values far apart)
      - Secondary: prefer higher (number_of_children + number_of_siblings) via weighted family_score
      - Tertiary: prefer smaller total size
    Schema assumption in input rows:
      (...composite key..., number_of_children, number_of_siblings, target_column, estimated_size)

    Output rows exclude the two family columns:
      (...composite key..., target_column, estimated_size)

    If fewer than X rows can be returned while meeting constraints, returns fewer (possibly 0).
    """
    if not rows:
        return []

    # ---- Indices: last 4 are (children, siblings, value, size) ----
    if headers is not None and len(headers) >= 4:
        L = len(headers)
    else:
        L = len(rows[0])
    children_index = L - 4
    siblings_index = L - 3
    value_index    = L - 2
    size_index     = L - 1

    # ---- Normalize sizes to Decimal ----
    def to_decimal(x: Any) -> Decimal:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, int):
            return Decimal(x)
        if isinstance(x, float):
            return Decimal(str(x))
        if isinstance(x, str):
            return Decimal(x)
        raise TypeError(f"Unsupported size type: {type(x)} (value={x})")

    threshold = to_decimal(x_threshold)

    # ---- Robust children/siblings numeric parsing ----
    def to_int_safe(x: Any) -> int:
        if x is None:
            return 0
        if isinstance(x, bool):
            return int(x)  # True=1, False=0
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(round(x))
        if isinstance(x, Decimal):
            return int(x)
        if isinstance(x, str):
            try:
                return int(float(x))
            except Exception:
                return 0
        return 0

    def family_score(children: Any, siblings: Any) -> float:
        c = to_int_safe(children)
        s = to_int_safe(siblings)
        return children_weight * c + siblings_weight * s

    # ---- Helper: strip family columns from output ----
    def strip_family_cols(row: Row) -> Row:
        # Keep everything up to children_index, then append (value, size)
        return tuple(list(row[:children_index]) + [row[value_index], row[size_index]])

    # ---- Parse and filter ----
    processed = []
    for r in rows:
        try:
            size = to_decimal(r[size_index])
        except Exception:
            continue  # skip unparsable sizes
        processed.append({
            "row": r,
            "value": r[value_index],
            "size": size,
            "children": r[children_index],
            "siblings": r[siblings_index],
            "family": family_score(r[children_index], r[siblings_index]),
        })

    if not processed:
        return []

    # ---- If no single row fits, return [] ----
    if min(p["size"] for p in processed) > threshold:
        return []

    # ---- Type detection (ignore None values) ----
    values = [p["value"] for p in processed]
    non_none_vals = [v for v in values if v is not None]

    def is_all_bool(vs):    return all(isinstance(v, bool) for v in vs)
    def is_all_str(vs):     return all(isinstance(v, str) for v in vs)
    def is_all_date_like(vs): return all(isinstance(v, (date, datetime)) for v in vs)
    def is_all_numeric(vs): return all((isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)) for v in vs)

    # ---- Route to strategy (diversity-first) ----
    if non_none_vals and is_all_bool(non_none_vals):
        selected_rows_full = _select_booleans_diversity_first(processed, threshold, X)
    elif non_none_vals and is_all_str(non_none_vals):
        selected_rows_full = _select_strings_diversity_first(processed, threshold, X)
    elif non_none_vals and is_all_date_like(non_none_vals):
        selected_rows_full = _select_numeric_diversity_first(processed, threshold, X, is_date=True)
    elif non_none_vals and is_all_numeric(non_none_vals):
        selected_rows_full = _select_numeric_diversity_first(processed, threshold, X, is_date=False)
    else:
        # Mixed/unknown -> treat as labels (strings)
        selected_rows_full = _select_strings_diversity_first(processed, threshold, X)

    # Strip family columns in the final output
    return [strip_family_cols(r) for r in selected_rows_full]


# ----------------------- Strategy Implementations ----------------------- #

def _best_effort_fill(processed: List[Dict], threshold: Decimal, X: int) -> List[Row]:
    """Fallback: pack up to X rows maximizing family score, tie-break by smaller size."""
    out = []
    total = Decimal(0)
    for p in sorted(processed, key=lambda x: (-x["family"], x["size"])):
        if total + p["size"] <= threshold:
            out.append(p["row"])
            total += p["size"]
            if len(out) >= X:
                break
    return out


def _select_booleans_diversity_first(processed: List[Dict], threshold: Decimal, X: int) -> List[Row]:
    """
    Booleans (diversity-first):
      - Require both True and False when possible.
      - Start with best diverse pair (max family; tie-break smaller size).
      - Add more while balancing counts and respecting threshold.
      - If only one class exists, return best-effort fill.
    """
    group = {True: [], False: []}
    for p in processed:
        group[p["value"]].append(p)

    has_true = len(group[True]) > 0
    has_false = len(group[False]) > 0

    if not (has_true and has_false):
        return _best_effort_fill(processed, threshold, X)

    for k in [True, False]:
        group[k].sort(key=lambda x: (-x["family"], x["size"]))

    # Best feasible diverse pair: family first, then smaller total size
    best_pair = None
    for t in group[True][:20]:
        for f in group[False][:20]:
            total = t["size"] + f["size"]
            if total <= threshold:
                fam = t["family"] + f["family"]
                if (
                    best_pair is None
                    or fam > best_pair[0]
                    or (fam == best_pair[0] and total < best_pair[1])
                ):
                    best_pair = (fam, total, [t, f])

    if best_pair is None:
        return []  # cannot even fit one from each class

    selected_objs = best_pair[2][:]
    total_size = best_pair[1]
    count_true = 1
    count_false = 1

    # Indices after possibly consuming the top items
    def advance_idx(group_list, picked_obj):
        return 1 if group_list and group_list[0] is picked_obj else 0

    idx_true = advance_idx(group[True], selected_objs[0])
    idx_false = advance_idx(group[False], selected_objs[1])

    # Grow up to X while balancing counts and preferring family
    while len(selected_objs) < X:
        take_true = count_true < count_false
        cand_list = group[True] if take_true else group[False]
        idx = idx_true if take_true else idx_false

        added = False
        if idx < len(cand_list):
            cand = cand_list[idx]
            if total_size + cand["size"] <= threshold:
                selected_objs.append(cand)
                total_size += cand["size"]
                if take_true:
                    count_true += 1
                    idx_true += 1
                else:
                    count_false += 1
                    idx_false += 1
                added = True
            else:
                # Try other side
                other_list = group[False] if take_true else group[True]
                other_idx = idx_false if take_true else idx_true
                if other_idx < len(other_list):
                    cand2 = other_list[other_idx]
                    if total_size + cand2["size"] <= threshold:
                        selected_objs.append(cand2)
                        total_size += cand2["size"]
                        if take_true:
                            count_false += 1
                            idx_false += 1
                        else:
                            count_true += 1
                            idx_true += 1
                        added = True
        if not added:
            break

    return [o["row"] for o in selected_objs]


def _select_strings_diversity_first(processed: List[Dict], threshold: Decimal, X: int) -> List[Row]:
    """
    Strings (diversity-first):
      - Choose at most one representative per distinct label.
      - Representative = highest family (tie-break smaller size).
      - Greedily pack distinct labels under threshold by family desc.
    """
    by_label: Dict[str, List[Dict]] = {}
    for p in processed:
        by_label.setdefault(p["value"], []).append(p)

    reps = []
    for label, items in by_label.items():
        items.sort(key=lambda x: (-x["family"], x["size"]))
        reps.append(items[0])

    reps.sort(key=lambda x: (-x["family"], x["size"]))

    out = []
    total = Decimal(0)
    for r in reps:
        if total + r["size"] <= threshold:
            out.append(r["row"])
            total += r["size"]
            if len(out) >= X:
                break
    return out


def _select_numeric_diversity_first(processed: List[Dict], threshold: Decimal, X: int, is_date: bool) -> List[Row]:
    """
    Numeric/Date (diversity-first):
      - Primary: maximize spread (sum of pairwise distances).
      - Secondary: maximize total family.
      - Tertiary: minimize total size.
      - Build best pair then greedily add with largest spread gain; tie-break family gain, then smaller size.
      - If no pair fits, return best singleton by family if it fits; else [].
    """
    def to_float(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, datetime):
            return v.timestamp()
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day).timestamp()
        raise TypeError(f"Unsupported numeric/date value type: {type(v)}")

    entries = []
    for p in processed:
        try:
            val_num = to_float(p["value"])
        except Exception:
            continue
        e = dict(p)
        e["val_num"] = val_num
        entries.append(e)

    if not entries:
        return []

    # Candidate pool: smallest-by-size + evenly spaced by value
    entries.sort(key=lambda x: x["val_num"])
    K = min(50, len(entries))
    smallest = sorted(entries, key=lambda x: x["size"])[:K]

    N_spots = max(10, X * 3)
    if len(entries) <= N_spots + 1:
        spaced = entries
    else:
        step = (len(entries) - 1) / N_spots
        indices = sorted({int(round(i * step)) for i in range(N_spots + 1)})
        spaced = [entries[i] for i in indices]

    seen = set()
    pool = []
    for item in smallest + spaced:
        key = (item["row"], item["val_num"], item["size"])
        if key not in seen:
            seen.add(key)
            pool.append(item)

    def total_spread(points):
        vs = [p["val_num"] for p in points]
        s = 0.0
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                s += abs(vs[i] - vs[j])
        return s

    def total_family(points):
        return sum(p["family"] for p in points)

    # Best pair: spread first, then family, then size
    best_pair = None
    for a, b in combinations(pool, 2):
        total = a["size"] + b["size"]
        if total <= threshold:
            dist = abs(a["val_num"] - b["val_num"])
            fam  = a["family"] + b["family"]
            if (
                best_pair is None
                or dist > best_pair[0]
                or (dist == best_pair[0] and fam > best_pair[1])
                or (dist == best_pair[0] and fam == best_pair[1] and total < best_pair[2])
            ):
                best_pair = (dist, fam, total, [a, b])

    if best_pair is None:
        best_single = min(pool, key=lambda x: (-x["family"], x["size"]))
        return [best_single["row"]] if best_single["size"] <= threshold else []

    selected = best_pair[3][:]
    total_size = best_pair[2]

    # Greedy additions: spread gain, then family gain, then smaller size
    while len(selected) < X:
        best_gain = None
        cur_spread = total_spread(selected)
        cur_family = total_family(selected)
        for cand in pool:
            if cand in selected:
                continue
            if total_size + cand["size"] > threshold:
                continue
            new_spread = total_spread(selected + [cand])
            new_family = cur_family + cand["family"]
            gain_spread = new_spread - cur_spread
            gain_family = new_family - cur_family
            if (
                best_gain is None
                or gain_spread > best_gain[0]
                or (gain_spread == best_gain[0] and gain_family > best_gain[1])
                or (gain_spread == best_gain[0] and gain_family == best_gain[1] and cand["size"] < best_gain[2])
            ):
                best_gain = (gain_spread, gain_family, cand["size"], cand)
        if best_gain is None:
            break
        cand = best_gain[3]
        selected.append(cand)
        total_size += cand["size"]

    return [s["row"] for s in selected]



