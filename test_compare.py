import sys
import pandas as pd
from app.pedigree.calculator import PedigreeCalculator
from app.pedigree.analysis import analyzer

# Load sample data
df = pd.read_csv('app/pedigree/sample_data.csv', sep=';' if ';' in open('app/pedigree/sample_data.csv').readline() else ',')
print(f"Loaded {len(df)} records from sample_data.csv")

# Ensure proper columns
df.columns = df.columns.str.strip().str.lower()
col_map = {}
for c in df.columns:
    if c in ['animal_id', 'egyed', 'azonosito', 'id']: col_map[c] = 'animal_id'
    elif c in ['sire_id', 'apa', 'apa_id']: col_map[c] = 'sire_id'
    elif c in ['dam_id', 'anya', 'anya_id']: col_map[c] = 'dam_id'
df = df.rename(columns=col_map)
print("Mapped columns:", df.columns)

calc = PedigreeCalculator(df)
calc._ensure_meuwissen_initialized()

test_animals = df[df['sire_id'].notna() & df['dam_id'].notna()]

print("\n--- COMPARISON ---")
for _, row in test_animals.iterrows():
    sire = str(row['sire_id'])
    if sire.endswith('.0'): sire = sire[:-2]
    dam = str(row['dam_id'])
    if dam.endswith('.0'): dam = dam[:-2]
    
    df_map = {str(r.animal_id): (str(r.sire_id) if pd.notna(r.sire_id) else None, 
                                 str(r.dam_id) if pd.notna(r.dam_id) else None)
              for r in df.itertuples()}
    
    for k, v in df_map.items():
        s, d = v
        if s and s.endswith('.0'): s = s[:-2]
        if d and d.endswith('.0'): d = d[:-2]
        df_map[k] = (s, d)
        
    sire_ancestors, dam_ancestors = {sire}, {dam}
    q_sire, q_dam = [sire], [dam]
    
    head = 0
    while head < len(q_sire):
        curr = q_sire[head]
        head += 1
        p = df_map.get(curr)
        if p:
            if p[0] and p[0] not in sire_ancestors:
                sire_ancestors.add(p[0])
                q_sire.append(p[0])
            if p[1] and p[1] not in sire_ancestors:
                sire_ancestors.add(p[1])
                q_sire.append(p[1])
                
    head = 0
    while head < len(q_dam):
        curr = q_dam[head]
        head += 1
        p = df_map.get(curr)
        if p:
            if p[0] and p[0] not in dam_ancestors:
                dam_ancestors.add(p[0])
                q_dam.append(p[0])
            if p[1] and p[1] not in dam_ancestors:
                dam_ancestors.add(p[1])
                q_dam.append(p[1])
                
    common_ancestors = sire_ancestors.intersection(dam_ancestors)
    
    total_path = 0.0
    for ancestor_id in common_ancestors:
        anc_inbreeding = calc.get_inbreeding_meuwissen(ancestor_id)
        
        sire_paths = analyzer.find_all_paths_to_ancestor(df_map, sire, ancestor_id)
        dam_paths = analyzer.find_all_paths_to_ancestor(df_map, dam, ancestor_id)
        
        for n in sire_paths:
            for m in dam_paths:
                total_path += (0.5)**(n + m + 1) * (1 + anc_inbreeding)
                
    total_fast = calc.calculate_coancestry(sire, dam)
    
    diff = abs(total_path - total_fast)
    if diff > 1e-6:
        print(f"Mismatch! Sire: {sire}, Dam: {dam} -> Path: {total_path:.6f} | Fast: {total_fast:.6f} | Diff: {diff:.6f}")
    else:
        print(f"Match! Sire: {sire}, Dam: {dam} -> {total_fast:.6f}")

print("Done comparing.")
