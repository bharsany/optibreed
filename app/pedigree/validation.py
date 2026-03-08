import pandas as pd


def validate_pedigree(df):
    """
    Runs a suite of consistency checks on a pedigree DataFrame.
    Designed to handle very large pedigrees (hundreds of thousands of animals)
    by using iterative (non-recursive) algorithms to avoid Python stack limits.
    
    Returns a list of dicts:
        {'animal_id': '...', 'issue_type': '...', 'description': '...'}
    """
    issues = []
    
    # --- 1. Build the in-memory map ---
    df_map = {}
    for row in df.itertuples():
        s = str(row.sire_id).strip() if pd.notna(row.sire_id) else None
        d = str(row.dam_id).strip() if pd.notna(row.dam_id) else None
        if s and s.endswith('.0'): s = s[:-2]
        if d and d.endswith('.0'): d = d[:-2]
        aid = str(row.animal_id).strip()
        if aid.endswith('.0'): aid = aid[:-2]
        df_map[aid] = (s, d)

    animal_ids = set(df_map.keys())
    sire_ids = set()
    dam_ids = set()
    for aid, (sire, dam) in df_map.items():
        if sire:
            sire_ids.add(sire)
        if dam:
            dam_ids.add(dam)

    # --- 2. Missing parents (Dangling IDs) ---
    missing_sires = sire_ids - animal_ids
    missing_dams = dam_ids - animal_ids
    
    for aid, (sire, dam) in df_map.items():
        if sire in missing_sires:
            issues.append({
                'animal_id': aid,
                'issue_type': 'Hiányzó szülő (Apa)',
                'description': f'Az apa ({sire}) nem szerepel önálló egyedként a nyilvántartásban.'
            })
        if dam in missing_dams:
            issues.append({
                'animal_id': aid,
                'issue_type': 'Hiányzó szülő (Anya)',
                'description': f'Az anya ({dam}) nem szerepel önálló egyedként a nyilvántartásban.'
            })

    # --- 3. Self-mating / Self-parenting ---
    for aid, (sire, dam) in df_map.items():
        if aid == sire:
            issues.append({
                'animal_id': aid,
                'issue_type': 'Ön-szülőség',
                'description': 'Az egyed saját magaként van megadva apaként.'
            })
        if aid == dam:
            issues.append({
                'animal_id': aid,
                'issue_type': 'Ön-szülőség',
                'description': 'Az egyed saját magaként van megadva anyaként.'
            })

    # --- 4. Gender inconsistency: ID appears both as sire and dam ---
    gender_conflicts = sire_ids.intersection(dam_ids)
    for conflict_id in gender_conflicts:
        issues.append({
            'animal_id': conflict_id,
            'issue_type': 'Nemi ellentmondás',
            'description': f'Az egyed egyaránt szerepel apaként és anyaként a nyilvántartásban.'
        })

    # --- 5. Circular references using iterative Kahn's topological sort ---
    # Any animal NOT in the topologically sorted output has a cycle.
    # This works for any size pedigree without recursion.
    in_degree = {aid: 0 for aid in df_map}
    children = {aid: [] for aid in df_map}
    
    for aid, (sire, dam) in df_map.items():
        for parent in (sire, dam):
            if parent and parent in df_map:
                in_degree[aid] += 1
                children[parent].append(aid)
    
    queue = [aid for aid, deg in in_degree.items() if deg == 0]
    visited_count = 0
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        visited_count += 1
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    
    # Any node with in_degree > 0 is part of a cycle
    cycle_members = [aid for aid, deg in in_degree.items() if deg > 0]
    max_loop_reports = 10
    reported = 0
    for aid in cycle_members:
        if reported >= max_loop_reports:
            issues.append({
                'animal_id': f'({len(cycle_members) - max_loop_reports} további egyed)',
                'issue_type': 'Körkörös hivatkozás (Pedigré hurok)',
                'description': 'A fennmaradó érintett egyedek listáját az Excel-exportban tekintheti meg.'
            })
            break
        issues.append({
            'animal_id': aid,
            'issue_type': 'Körkörös hivatkozás (Pedigré hurok)',
            'description': 'Ez az egyed egy körkörös referencia-láncban szerepel, ami a szülőfában időutazást jelent.'
        })
        reported += 1

    return issues
