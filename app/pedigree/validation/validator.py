import pandas as pd

def validate_pedigree(data):
    """
    Validates the pedigree data using vectorized operations for efficiency.

    Args:
        data (pd.DataFrame): The raw pedigree data from the CSV.

    Returns:
        list: A list of validation errors.
    """
    errors = []
    df = data.copy()

    # 1. Check for required columns
    required_columns = ['animal_id', 'dam_id', 'sire_id']
    for col in required_columns:
        if col not in df.columns:
            errors.append(f'Missing required column: {col}')
    if errors:
        return errors

    # 2. Coerce IDs to a common, nullable numeric type.
    for col in required_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Report any rows where animal_id could not be converted to a number
    if df['animal_id'].isnull().any():
        invalid_rows = df[df['animal_id'].isnull()].index.tolist()
        for idx in invalid_rows:
            errors.append(f"Row {idx + 2}: 'animal_id' must be a number.")
        return errors

    # Convert to nullable integers now that we know they are numeric
    try:
        for col in required_columns:
            df[col] = df[col].astype('Int64')
    except Exception as e:
        errors.append(f"Could not convert ID columns to integers: {e}")
        return errors

    # 3. Check for unique animal_id
    if not df['animal_id'].is_unique:
        duplicates = df[df.duplicated('animal_id', keep=False)]['animal_id'].unique().tolist()
        errors.append(f"The following 'animal_id' values are duplicated: {duplicates}.")

    # 4. Check for self-references
    if (df['animal_id'] == df['dam_id']).any():
        errors.append("An animal cannot be its own dam.")
    if (df['animal_id'] == df['sire_id']).any():
        errors.append("An animal cannot be its own sire.")

    # 5. Check if dam and sire are the same
    if (df['dam_id'].notna() & (df['dam_id'] == df['sire_id'])).any():
        errors.append("An animal's dam and sire cannot be the same.")

    # 6. Vectorized check for parent existence
    valid_animal_ids = set(df['animal_id'])

    invalid_dams = df[df['dam_id'].notna() & ~df['dam_id'].isin(valid_animal_ids)]
    for index, row in invalid_dams.iterrows():
        errors.append(f"Row {index + 2}: dam_id '{row['dam_id']}' is not a valid animal_id.")

    invalid_sires = df[df['sire_id'].notna() & ~df['sire_id'].isin(valid_animal_ids)]
    for index, row in invalid_sires.iterrows():
        errors.append(f"Row {index + 2}: sire_id '{row['sire_id']}' is not a valid animal_id.")

    return errors
