
import pandas as pd
import numpy as np
from app.pedigree.calculator import PedigreeCalculator

try:
    df = pd.read_csv('temp_pedigree.csv', dtype=str).rename(columns=lambda x: x.strip().lower())

    df['animal_id'] = df['orszagkod'].fillna('') + df['fulszam'].fillna('')
    df['sire_id'] = df['apaorsko'].fillna('') + df['apafulszam'].fillna('')
    df['dam_id'] = df['anyaorsko'].fillna('') + df['anyafulsza'].fillna('')
    df['sire_id'] = df['sire_id'].replace('', None)
    df['dam_id'] = df['dam_id'].replace('', None)

    final_df = df[['animal_id', 'sire_id', 'dam_id']].copy()
    final_df = final_df.replace({np.nan: None})

    calculator = PedigreeCalculator(final_df)
    animal_id_to_calculate = 'HU7019140314'
    
    if animal_id_to_calculate in calculator.df['animal_id'].values:
        inbreeding_coefficient = calculator.get_inbreeding_meuwissen(animal_id_to_calculate)
        print(f"The Meuwissen-Luo inbreeding coefficient for animal {animal_id_to_calculate} is: {inbreeding_coefficient:.4f}")
    else:
        print(f"Error: Animal with ID {animal_id_to_calculate} not found in the pedigree file.")
except Exception as e:
    print(f"An error occurred: {e}")

