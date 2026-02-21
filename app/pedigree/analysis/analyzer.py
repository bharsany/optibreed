
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

# --- ALGORITHM 1: Tabular Method (Meuwissen-Luo) ---


def calculate_inbreeding_tabular(df, progress_callback=None, core_animal_ids=None):
    """
    Calculates inbreeding coefficients for all animals in the dataframe
    using the tabular method (Meuwissen-Luo), which is robust and efficient.

    Args:
        df: Pedigree dataframe
        progress_callback: Optional callable(current, total) for progress updates
        core_animal_ids: Optional list of core animal IDs to filter to. If provided,
                        only core animals and their ancestors are calculated.
    """
    import sys
    import time
    t_start = time.time()

    # The animal_id is now a string, so the numeric conversion has been removed.
    # Ensure indices are unique
    df = df.drop_duplicates(subset=['animal_id']).set_index('animal_id').copy()

    # If core animals are specified, filter to include only them and their ancestors
    if core_animal_ids:
        # Only include core animals that actually exist in the dataframe
        core_animals_in_df = [
            aid for aid in core_animal_ids if aid in df.index]

        t_ancestor = time.time()
        relevant_animals = find_all_ancestors(
            df.reset_index(), core_animals_in_df)
        print(
            f"Time to find ancestors: {time.time() - t_ancestor:.2f}s", file=sys.stderr)

        df_filtered = df.loc[df.index.isin(relevant_animals)].copy()
        print(
            f"Meuwissen optimization: Found {len(core_animals_in_df)} out of {len(core_animal_ids)} requested core animals. Using {len(df_filtered)} total animals ({len(core_animals_in_df)} core + {len(relevant_animals) - len(core_animals_in_df)} ancestors) instead of {len(df)}", file=sys.stderr)
    else:
        df_filtered = df.copy()
        print(
            f"Meuwissen: No optimization - calculating for all {len(df)} animals", file=sys.stderr)

    # CRITICAL: Sort by birth_year for correct topological order (must process parents before offspring)
    # If no birth_year, use alphabetical as fallback
    t_sort = time.time()
    if 'birth_year' in df_filtered.columns:
        try:
            df_filtered['birth_year_numeric'] = pd.to_numeric(
                df_filtered['birth_year'], errors='coerce')
            df_filtered = df_filtered.sort_values(
                'birth_year_numeric', na_position='first')
            df_filtered = df_filtered.drop('birth_year_numeric', axis=1)
        except:
            # Fallback to alphabetical if conversion fails
            df_filtered = df_filtered.sort_index()
    else:
        df_filtered = df_filtered.sort_index()

    df_filtered = df_filtered.reset_index().set_index('animal_id')
    print(
        f"Time to sort and reset index: {time.time() - t_sort:.2f}s", file=sys.stderr)

    animal_pos = {animal_id: i for i,
                  animal_id in enumerate(df_filtered.index)}
    n = len(df_filtered.index)
    A = np.zeros((n, n))

    t_map = time.time()
    # Pre-build parent lookup dictionary for O(1) access instead of using slow .loc
    parent_map = {row.animal_id: (row.sire_id, row.dam_id)
                  for row in df_filtered.reset_index().itertuples()}
    print(
        f"Time to build parent_map: {time.time() - t_map:.2f}s", file=sys.stderr)

    t_compute = time.time()
    for i, animal_id in enumerate(df_filtered.index):
        sire_id, dam_id = parent_map.get(animal_id, (None, None))

        # Get positions, handling cases where parents are not in the pedigree
        sire_pos = animal_pos.get(sire_id, -1) if pd.notna(sire_id) else -1
        dam_pos = animal_pos.get(dam_id, -1) if pd.notna(dam_id) else -1

        # Both parents known
        if sire_pos != -1 and dam_pos != -1:
            # Get coancestry between parents
            coancestry = A[sire_pos,
                           dam_pos] if sire_pos < dam_pos else A[dam_pos, sire_pos]
            A[i, i] = 1 + 0.5 * coancestry
            # Set relationship with other animals
            for j in range(i):
                val = 0.5 * (A[sire_pos, j] + A[dam_pos, j])
                A[i, j] = A[j, i] = val
        # Only one parent known
        elif sire_pos != -1 or dam_pos != -1:
            parent_pos = sire_pos if sire_pos != -1 else dam_pos
            A[i, i] = 1.0
            # Set relationship with other animals
            for j in range(i):
                val = 0.5 * A[parent_pos, j]
                A[i, j] = A[j, i] = val
        # No parents known (base animal)
        else:
            A[i, i] = 1.0

        # Emit progress every 50 animals or at the end for more frequent updates
        if progress_callback and (i % 50 == 0 or i == n - 1):
            progress_callback(i + 1, n)

    print(
        f"Time for matrix computation loop: {time.time() - t_compute:.2f}s", file=sys.stderr)

    t_extract = time.time()
    inbreeding_coeffs = {animal_id: A[i, i] -

                         1 for i, animal_id in enumerate(df_filtered.index)}
    print(
        f"Time to extract inbreeding coefficients: {time.time() - t_extract:.2f}s", file=sys.stderr)
    print(
        f"TOTAL Meuwissen calculation time: {time.time() - t_start:.2f}s", file=sys.stderr)
    return inbreeding_coeffs

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
