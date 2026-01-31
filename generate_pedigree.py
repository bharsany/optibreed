import random
import sys

def generate_complex_pedigree(num_animals=100):
    """
    Generates and prints a complex, inbred pedigree in CSV format, 
    including farm_id and gender.
    """
    print("animal_id,dam_id,sire_id,farm_id,gender")

    farm_ids = [f"FARM-{chr(65+i)}" for i in range(7)]
    animal_farms = {}
    animal_genders = {}
    pedigree = {}

    # --- Generation 1: Founders ---
    founders = list(range(1, 11))
    for i, founder in enumerate(founders):
        farm = farm_ids[i % len(farm_ids)]
        gender = random.choice(['M', 'F'])
        print(f"{founder},,,{farm},{gender}")
        pedigree[founder] = (None, None)
        animal_farms[founder] = farm
        animal_genders[founder] = gender
    
    next_id = 11

    def get_offspring_farm(dam_id, sire_id):
        dam_farm = animal_farms.get(dam_id)
        sire_farm = animal_farms.get(sire_id)
        if sire_farm is None or dam_farm == sire_farm:
            return dam_farm if random.random() < 0.9 else random.choice(farm_ids)
        else:
            return random.choice([dam_farm, sire_farm])

    # --- Subsequent Generations ---
    while next_id <= num_animals:
        try:
            available_dams = [id for id, sex in animal_genders.items() if sex == 'F']
            available_sires = [id for id, sex in animal_genders.items() if sex == 'M']

            if not available_dams or not available_sires:
                continue # Cannot create offspring if one gender is missing

            dam = random.choice(available_dams)
            sire = random.choice(available_sires)

            # Simple check to avoid immediate selfing if lists are small, though not strictly disallowed
            if dam == sire:
                 continue

            farm = get_offspring_farm(dam, sire)
            gender = random.choice(['M', 'F'])
            
            print(f"{next_id},{dam},{sire},{farm},{gender}")
            pedigree[next_id] = (dam, sire)
            animal_farms[next_id] = farm
            animal_genders[next_id] = gender
            next_id += 1
        except IndexError:
            continue
        
if __name__ == "__main__":
    # To run this from command line and save to a file:
    # python generate_pedigree.py > complex_pedigree_100.csv
    generate_complex_pedigree()
