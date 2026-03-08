import sys
import pandas as pd
from app.pedigree.calculator import PedigreeCalculator

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

print("Meuwissen Diagonal IBCs:")
for aid, ibc in calc.F_meuwissen_cache.items():
    if ibc > 0:
        print(f"Animal {aid}: {ibc:.6f}")
        
print("\nPath Method IBCs (Simulated from offspring perspective):")
from app.pedigree.analysis import analyzer
# The path method in the app calculates IBC for an animal by finding paths to common ancestors of its parents.
path_cache = {}
for aid in df['animal_id']:
    val = analyzer.calculate_inbreeding_path_based_for_animal(df, str(aid), path_cache)
    if val > 0:
        print(f"Animal {aid}: {val:.6f}")

