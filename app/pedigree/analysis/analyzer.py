
import pandas as pd
import numpy as np

# --- UTILITY FUNCTIONS ---


def find_all_ancestors(df, animal_ids):
    """
    Finds all ancestors of a given set of animals using BFS.
    Returns a set of all ancestor IDs plus the original animals.
    """
    if not animal_ids:
        return set()

    # Build df_map for efficient parent lookup
    df_map = {row.animal_id: (row.sire_id, row.dam_id)
              for row in df.itertuples()}

    ancestors = set(animal_ids)
    queue = list(animal_ids)
    head = 0

    while head < len(queue):
        current_id = queue[head]
        head += 1
        parents = df_map.get(current_id)
        if parents:
            sire_id, dam_id = parents
            if pd.notna(sire_id) and sire_id not in ancestors:
                ancestors.add(sire_id)
                queue.append(sire_id)
            if pd.notna(dam_id) and dam_id not in ancestors:
                ancestors.add(dam_id)
                queue.append(dam_id)

    return ancestors


# --- Meuwissen-Luo Inbreeding Calculation (Optimized Diagonal Algorithm) ---



def calculate_inbreeding_diagonal(df, progress_callback=None, core_animal_ids=None):
    """
    Optimized Meuwissen & Luo (1992) diagonal algorithm.
    Computes inbreeding coefficients without building the full N×N relationship matrix.
    Uses O(N) space instead of O(N²), making it feasible for very large pedigrees.

    For each animal, it traces back through ancestors using a sparse max-heap approach,
    accumulating path contributions and computing F = sum(c_j^2 * d_j) - 1.
    """
    import sys
    import time
    import heapq

    t_start = time.time()

    df = df.drop_duplicates(subset=['animal_id']).set_index('animal_id').copy()

    if core_animal_ids:
        core_animals_in_df = [aid for aid in core_animal_ids if aid in df.index]
        relevant_animals = find_all_ancestors(df.reset_index(), core_animals_in_df)
        df_filtered = df.loc[df.index.isin(relevant_animals)].copy()
        print(
            f"Diagonal: {len(df_filtered)} animals ({len(core_animals_in_df)} core + "
            f"{len(df_filtered) - len(core_animals_in_df)} ancestors) from {len(df)} total",
            file=sys.stderr)
    else:
        df_filtered = df.copy()
        print(f"Diagonal: calculating for all {len(df)} animals", file=sys.stderr)

    # Sort by birth_year for topological order (parents before offspring)
    t_sort = time.time()
    if 'birth_year' in df_filtered.columns:
        try:
            df_filtered['birth_year_numeric'] = pd.to_numeric(
                df_filtered['birth_year'], errors='coerce')
            df_filtered = df_filtered.sort_values(
                'birth_year_numeric', na_position='first')
            df_filtered = df_filtered.drop('birth_year_numeric', axis=1)
        except Exception:
            df_filtered = df_filtered.sort_index()
    else:
        df_filtered = df_filtered.sort_index()

    df_filtered = df_filtered.reset_index().set_index('animal_id')
    print(f"Diagonal sort time: {time.time() - t_sort:.2f}s", file=sys.stderr)

    animals = list(df_filtered.index)
    n = len(animals)
    animal_pos = {aid: i for i, aid in enumerate(animals)}

    # Build parent position map
    parent_pos = {}
    for row in df_filtered.reset_index().itertuples():
        pos = animal_pos[row.animal_id]
        sp = animal_pos.get(row.sire_id, -1) if pd.notna(row.sire_id) else -1
        dp = animal_pos.get(row.dam_id, -1) if pd.notna(row.dam_id) else -1
        parent_pos[pos] = (sp, dp)

    F = [0.0] * n   # Inbreeding coefficients
    d = [0.0] * n   # Mendelian sampling variances

    t_compute = time.time()

    for i in range(n):
        si, di_p = parent_pos.get(i, (-1, -1))

        # Mendelian sampling variance
        if si >= 0 and di_p >= 0:
            d[i] = 0.5 - 0.25 * (F[si] + F[di_p])
        elif si >= 0:
            d[i] = 0.75 - 0.25 * F[si]
        elif di_p >= 0:
            d[i] = 0.75 - 0.25 * F[di_p]
        else:
            d[i] = 1.0

        # Trace back through ancestors using sparse max-heap.
        # Process in descending position order to ensure all contributions
        # to an ancestor are accumulated before that ancestor is processed.
        contrib = {i: 1.0}
        heap = [-i]
        visited = set()
        fi = 0.0

        while heap:
            j = -heapq.heappop(heap)
            if j in visited:
                continue
            visited.add(j)

            c = contrib.get(j, 0.0)
            if c == 0.0:
                continue

            fi += c * c * d[j]

            sj, dj = parent_pos.get(j, (-1, -1))
            if sj >= 0 and sj not in visited:
                contrib[sj] = contrib.get(sj, 0.0) + 0.5 * c
                heapq.heappush(heap, -sj)
            if dj >= 0 and dj not in visited:
                contrib[dj] = contrib.get(dj, 0.0) + 0.5 * c
                heapq.heappush(heap, -dj)

        F[i] = fi - 1.0

        if progress_callback and (i % 50 == 0 or i == n - 1):
            progress_callback(i + 1, n)

    print(f"Diagonal computation time: {time.time() - t_compute:.2f}s", file=sys.stderr)

    result = {animals[i]: F[i] for i in range(n)}
    total_time = time.time() - t_start
    print(f"TOTAL Diagonal Meuwissen time: {total_time:.2f}s", file=sys.stderr)

    return result


# --- ALGORITHM 2: Path-finding Method ---


def find_all_paths_to_ancestor(df_map, start_id, end_id):
    """Finds all unique paths from a start animal to a specific ancestor."""
    all_paths = []

    # Queue for BFS: stores tuples of (current_animal_id, path_to_current)
    queue = [(start_id, [])]

    while queue:
        current_id, path = queue.pop(0)

        # Add current animal to path
        new_path = path + [current_id]

        # If we reached the target ancestor, store the path length and continue
        if current_id == end_id:
            all_paths.append(len(new_path) - 1)
            # Do not explore further up from the ancestor on this path
            continue

        # Get parents from the pre-built map
        parents = df_map.get(current_id)
        if parents:
            sire_id, dam_id = parents
            if pd.notna(sire_id):
                queue.append((sire_id, new_path))
            if pd.notna(dam_id):
                queue.append((dam_id, new_path))

    return all_paths


def _calculate_inbreeding_for_animal_path_based(df_map, animal_id, F_cache):
    """
    Internal recursive function to calculate IBC for a single animal.
    Uses a cache (F_cache) to store and retrieve already computed values.
    """
    if animal_id in F_cache:
        return F_cache[animal_id]

    parents = df_map.get(animal_id)
    if not parents or pd.isna(parents[0]) or pd.isna(parents[1]):
        F_cache[animal_id] = 0.0
        return 0.0

    sire_id, dam_id = parents

    # This is not a proper coancestry calculation, but follows the classic path-method logic
    # which finds common ancestors and sums their contributions.

    # Find ancestors for sire and dam
    q_sire, q_dam = [sire_id], [dam_id]
    sire_ancestors, dam_ancestors = {sire_id}, {dam_id}

    head = 0
    while head < len(q_sire):
        curr = q_sire[head]
        head += 1
        p = df_map.get(curr)
        if p:
            if pd.notna(p[0]) and p[0] not in sire_ancestors:
                sire_ancestors.add(p[0])
                q_sire.append(p[0])
            if pd.notna(p[1]) and p[1] not in sire_ancestors:
                sire_ancestors.add(p[1])
                q_sire.append(p[1])

    head = 0
    while head < len(q_dam):
        curr = q_dam[head]
        head += 1
        p = df_map.get(curr)
        if p:
            if pd.notna(p[0]) and p[0] not in dam_ancestors:
                dam_ancestors.add(p[0])
                q_dam.append(p[0])
            if pd.notna(p[1]) and p[1] not in dam_ancestors:
                dam_ancestors.add(p[1])
                q_dam.append(p[1])

    common_ancestors = sire_ancestors.intersection(dam_ancestors)

    total_inbreeding = 0.0
    for ancestor_id in common_ancestors:
        # Recursively calculate the ancestor's own inbreeding coefficient
        ancestor_inbreeding = _calculate_inbreeding_for_animal_path_based(
            df_map, ancestor_id, F_cache)

        # Find all paths from sire and dam to the common ancestor
        sire_paths = find_all_paths_to_ancestor(df_map, sire_id, ancestor_id)
        dam_paths = find_all_paths_to_ancestor(df_map, dam_id, ancestor_id)

        # Sum the contributions from this ancestor
        for n in sire_paths:
            for m in dam_paths:
                total_inbreeding += (0.5)**(n + m + 1) * \
                    (1 + ancestor_inbreeding)

    F_cache[animal_id] = total_inbreeding
    return total_inbreeding


def calculate_inbreeding_path_based_for_animal(df, animal_id, F_cache):
    """
    Public-facing function to calculate IBC for a single animal using the path method.
    It prepares a map for efficient parent lookup.
    """
    # Create a mapping for faster parent lookups
    df_map = {row.animal_id: (row.sire_id, row.dam_id)
              for row in df.itertuples()}
    return _calculate_inbreeding_for_animal_path_based(df_map, animal_id, F_cache)
