
import pandas as pd
import numpy as np

# --- ALGORITHM 1: Tabular Method (Meuwissen-Luo) ---

def calculate_inbreeding_tabular(df):
    """
    Calculates inbreeding coefficients for all animals in the dataframe
    using the tabular method (Meuwissen-Luo), which is robust and efficient.
    """
    df['animal_id'] = pd.to_numeric(df['animal_id'], errors='coerce').astype(int)
    df = df.set_index('animal_id').sort_index()
    animal_pos = {animal_id: i for i, animal_id in enumerate(df.index)}
    n = len(df.index)
    A = np.zeros((n, n))
    
    for i, animal_id in enumerate(df.index):
        sire_id = df.loc[animal_id, 'sire_id']
        dam_id = df.loc[animal_id, 'dam_id']
        sire_pos = animal_pos.get(sire_id, -1)
        dam_pos = animal_pos.get(dam_id, -1)
        
        if sire_pos != -1 and dam_pos != -1:
            A[i, i] = 1 + 0.5 * A[sire_pos, dam_pos]
            for j in range(i):
                val = 0.5 * (A[sire_pos, j] + A[dam_pos, j])
                A[i, j] = A[j, i] = val
        elif sire_pos != -1 or dam_pos != -1:
            parent_pos = sire_pos if sire_pos != -1 else dam_pos
            A[i, i] = 1.0
            for j in range(i):
                val = 0.5 * A[parent_pos, j]
                A[i, j] = A[j, i] = val
        else:
            A[i, i] = 1.0

    inbreeding_coeffs = {animal_id: A[i, i] - 1 for i, animal_id in enumerate(df.index)}
    return inbreeding_coeffs

# --- ALGORITHM 2: Path-finding Method (Corrected) ---

def find_all_paths_path_based(df, start_id, end_id):
    all_paths = []
    def find_paths_recursive(current_id, path):
        if pd.isna(current_id):
            return
        
        path.append(current_id)

        if current_id == end_id:
            all_paths.append(len(path) - 1)

        animal_row = df[df['animal_id'] == current_id]
        if not animal_row.empty:
            sire_id = animal_row['sire_id'].iloc[0]
            dam_id = animal_row['dam_id'].iloc[0]
            
            # Recurse on both parents without returning prematurely
            find_paths_recursive(sire_id, list(path))
            find_paths_recursive(dam_id, list(path))

    find_paths_recursive(start_id, [])
    return all_paths

def get_ancestors_path_based(df, animal_id):
    ancestors = set()
    q = [animal_id]
    while q:
        curr = q.pop(0)
        if pd.notna(curr) and curr not in ancestors:
            ancestors.add(curr)
            animal_row = df[df['animal_id'] == curr]
            if not animal_row.empty:
                q.append(animal_row['sire_id'].iloc[0])
                q.append(animal_row['dam_id'].iloc[0])
    return ancestors

def calculate_inbreeding_coefficient_path_based(df, animal_id, F_cache):
    if animal_id in F_cache:
        return F_cache[animal_id]

    animal_row = df[df['animal_id'] == animal_id]
    if animal_row.empty:
        return 0.0

    sire_id, dam_id = animal_row['sire_id'].iloc[0], animal_row['dam_id'].iloc[0]

    if pd.isna(sire_id) or pd.isna(dam_id):
        return 0.0

    sire_ancestors = get_ancestors_path_based(df, sire_id)
    dam_ancestors = get_ancestors_path_based(df, dam_id)
    common_ancestors = sire_ancestors.intersection(dam_ancestors)

    total_inbreeding = 0.0
    for ancestor_id in common_ancestors:
        # TRUE RECURSION: Calculate ancestor's inbreeding on the fly.
        ancestor_inbreeding = calculate_inbreeding_coefficient_path_based(df, ancestor_id, F_cache)
        
        sire_paths = find_all_paths_path_based(df, sire_id, ancestor_id)
        dam_paths = find_all_paths_path_based(df, dam_id, ancestor_id)
        
        for n in sire_paths:
            for m in dam_paths:
                total_inbreeding += (0.5)**(n + m + 1) * (1 + ancestor_inbreeding)

    F_cache[animal_id] = total_inbreeding
    return total_inbreeding

def calculate_inbreeding_path_based(df):
    F_cache = {}
    results = {}
    df['animal_id'] = pd.to_numeric(df['animal_id'], errors='coerce').astype(int)
    for col in ['sire_id', 'dam_id']:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    for animal_id in df['animal_id']:
        if animal_id not in F_cache:
            results[animal_id] = calculate_inbreeding_coefficient_path_based(df, animal_id, F_cache)
    
    # Return all cached results
    return F_cache
