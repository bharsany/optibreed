import pandas as pd

# --- ALGORITHM 1: Tabular Method (Meuwissen-Luo Equivalent) ---

# Memoization caches for the tabular method
F_cache = {}  
C_cache = {}  
parent_map = {} 
id_map = {}  
idx_map = {} # FIX: Correctly declare idx_map

def get_coancestry(i, j):
    if i > j: i, j = j, i
    if (i, j) in C_cache: return C_cache[(i, j)]
    if i == j: val = 0.5 * (1 + get_inbreeding(i))
    else:
        s, d = parent_map.get(j, (None, None))
        if s is None or d is None: val = 0.0
        else: val = 0.5 * (get_coancestry(i, s) + get_coancestry(i, d))
    C_cache[(i, j)] = val
    return val

def get_inbreeding(i):
    if i in F_cache: return F_cache[i]
    s, d = parent_map.get(i, (None, None))
    if s is None or d is None: val = 0.0
    else: val = get_coancestry(s, d)
    F_cache[i] = val
    return val

def calculate_inbreeding_tabular(df):
    global F_cache, C_cache, parent_map, id_map, idx_map
    F_cache.clear(); C_cache.clear(); parent_map.clear(); id_map.clear(); idx_map.clear()

    df_sorted = df.sort_values(by='animal_id').reset_index(drop=True)
    all_animals = list(df_sorted['animal_id'])
    id_map.update({orig_id: i for i, orig_id in enumerate(all_animals)})
    idx_map.update({i: orig_id for orig_id, i in id_map.items()})

    for idx, row in df_sorted.iterrows():
        parent_map[id_map[row['animal_id']]] = (id_map.get(row['sire_id']), id_map.get(row['dam_id']))

    for i in range(len(all_animals)): get_inbreeding(i)

    final_F = {idx_map[i]: f_val for i, f_val in F_cache.items()}
    for animal_id in df['animal_id']:
        if animal_id not in final_F: final_F[animal_id] = 0.0
    return final_F


# --- ALGORITHM 2: Path-finding Method ---

def get_ancestors_path_based(df, animal_id, ancestors=None):
    if ancestors is None: ancestors = set()
    animal_row = df[df['animal_id'] == animal_id]
    if animal_row.empty: return ancestors
    sire_id, dam_id = animal_row['sire_id'].iloc[0], animal_row['dam_id'].iloc[0]
    if pd.notna(sire_id): ancestors.add(sire_id); get_ancestors_path_based(df, sire_id, ancestors)
    if pd.notna(dam_id): ancestors.add(dam_id); get_ancestors_path_based(df, dam_id, ancestors)
    return ancestors

def find_path_length_path_based(df, start_id, end_id, path_len=0):
    if start_id == end_id: return path_len
    animal_row = df[df['animal_id'] == start_id]
    if animal_row.empty: return -1
    sire_id, dam_id = animal_row['sire_id'].iloc[0], animal_row['dam_id'].iloc[0]
    if pd.notna(sire_id):
        res = find_path_length_path_based(df, sire_id, end_id, path_len + 1)
        if res != -1: return res
    if pd.notna(dam_id):
        res = find_path_length_path_based(df, dam_id, end_id, path_len + 1)
        if res != -1: return res
    return -1

def calculate_inbreeding_coefficient_path_based(df, animal_id, F):
    if animal_id in F: return F[animal_id]
    animal_row = df[df['animal_id'] == animal_id]
    if animal_row.empty: return 0.0
    sire_id, dam_id = animal_row['sire_id'].iloc[0], animal_row['dam_id'].iloc[0]
    if pd.isna(sire_id) or pd.isna(dam_id): return 0.0
    if sire_id == dam_id: return 1 + calculate_inbreeding_coefficient_path_based(df, sire_id, F)

    sire_ancestors = get_ancestors_path_based(df.copy(), sire_id)
    dam_ancestors = get_ancestors_path_based(df.copy(), dam_id)
    common_ancestors = sire_ancestors.intersection(dam_ancestors)

    inbreeding_sum = 0.0
    for ancestor in common_ancestors:
        path_sire = find_path_length_path_based(df.copy(), sire_id, ancestor)
        path_dam = find_path_length_path_based(df.copy(), dam_id, ancestor)
        ancestor_inbreeding = calculate_inbreeding_coefficient_path_based(df, ancestor, F)
        inbreeding_sum += (0.5)**(path_sire + path_dam + 1) * (1 + ancestor_inbreeding)
    F[animal_id] = inbreeding_sum
    return inbreeding_sum

def calculate_inbreeding_path_based(df):
    F = {}
    df_copy = df.copy()
    df_copy['animal_id'] = df_copy['animal_id'].astype(int)
    df_copy['sire_id'] = pd.to_numeric(df_copy['sire_id'], errors='coerce')
    df_copy['dam_id'] = pd.to_numeric(df_copy['dam_id'], errors='coerce')
    for _, row in df_copy.iterrows():
        animal_id = row['animal_id']
        if animal_id not in F: calculate_inbreeding_coefficient_path_based(df_copy, animal_id, F)
    for animal_id in df_copy['animal_id']:
        if animal_id not in F: F[animal_id] = 0.0
    return F
