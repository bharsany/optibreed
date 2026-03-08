import sys
import pandas as pd
from app.pedigree.calculator import PedigreeCalculator
from app.pedigree.analysis import analyzer

df = pd.read_csv('app/pedigree/sample_data.csv', sep=';' if ';' in open('app/pedigree/sample_data.csv').readline() else ',')
df.columns = df.columns.str.strip().str.lower()
col_map = {}
for c in df.columns:
    if c in ['animal_id', 'egyed', 'azonosito', 'id']: col_map[c] = 'animal_id'
    elif c in ['sire_id', 'apa', 'apa_id']: col_map[c] = 'sire_id'
    elif c in ['dam_id', 'anya', 'anya_id']: col_map[c] = 'dam_id'
df = df.rename(columns=col_map)

calc = PedigreeCalculator(df)
calc._ensure_meuwissen_initialized()

print("Meuwissen Diagonal IBCs (Mathematically correct Tabular):")
for aid, ibc in calc.F_meuwissen_cache.items():
    if ibc > 0:
        print(f"Animal {aid}: {ibc:.6f}")
        
print("\nApp Path Method IBCs (Simulated from offspring perspective):")
from app.pedigree.analysis import analyzer

df_map = {str(r.animal_id): (str(r.sire_id) if pd.notna(r.sire_id) else None, 
                             str(r.dam_id) if pd.notna(r.dam_id) else None)
          for r in df.itertuples()}

for aid in df['animal_id']:
    aid = str(aid)
    parents = df_map.get(aid)
    if not parents or not parents[0] or not parents[1]:
        continue
    sire, dam = parents[0], parents[1]
    
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
                
    if total_path > 0:
        print(f"Animal {aid}: {total_path:.6f}")

