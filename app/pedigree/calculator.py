import pandas as pd
from .analysis import analyzer

class PedigreeCalculator:
    def __init__(self, df):
        """
        Initializes the calculator with a pedigree dataframe.
        The Meuwissen-Luo inbreeding coefficients are pre-calculated for speed.
        A cache is prepared for the traditional path-based calculation.
        """
        self.df = df.copy()
        # Standardize data types
        self.df['animal_id'] = pd.to_numeric(self.df['animal_id'], errors='coerce').astype(int)
        for col in ['sire_id', 'dam_id']:
            self.df[col] = pd.to_numeric(self.df[col], errors='coerce').astype('Int64')
        
        # Pre-calculate all Meuwissen-Luo IBCs for fast retrieval
        self.F_meuwissen_cache = analyzer.calculate_inbreeding_tabular(self.df)
        
        # Initialize a cache for the slower path-based results to avoid re-computation
        self.F_path_cache = {}

    def get_inbreeding_meuwissen(self, animal_id):
        """
        Retrieves the pre-calculated Meuwissen-Luo inbreeding coefficient for an animal.
        """
        return self.F_meuwissen_cache.get(animal_id, 0.0)

    def get_inbreeding_traditional(self, animal_id):
        """
        Calculates the inbreeding coefficient for a single animal using the 
        traditional path-based algorithm. Caches results to speed up subsequent calls.
        """
        # It's critical that the F_path_cache is passed to and updated by the analyzer.
        return analyzer.calculate_inbreeding_path_based_for_animal(
            self.df, animal_id, self.F_path_cache
        )

    def calculate_coancestry(self, sire_id, dam_id):
        """
        Calculates the coancestry between a sire and a dam, which is equivalent
        to the inbreeding coefficient of their hypothetical offspring.
        
        For performance during mating simulations, this method uses the fast, 
        pre-calculated Meuwissen-Luo IBCs for the F-value of common ancestors.
        """
        sire_id, dam_id = int(sire_id), int(dam_id)

        # A map is needed for efficient path finding.
        df_map = {row.animal_id: (row.sire_id, row.dam_id) for row in self.df.itertuples()}

        # Find all ancestors for both the sire and the dam to identify common ones.
        q_sire, q_dam = [sire_id], [dam_id]
        sire_ancestors, dam_ancestors = {sire_id}, {dam_id}
        
        head = 0
        while head < len(q_sire):
            curr = q_sire[head]; head+=1
            p = df_map.get(curr)
            if p: 
                if pd.notna(p[0]) and p[0] not in sire_ancestors: sire_ancestors.add(p[0]); q_sire.append(p[0])
                if pd.notna(p[1]) and p[1] not in sire_ancestors: sire_ancestors.add(p[1]); q_sire.append(p[1])

        head = 0
        while head < len(q_dam):
            curr = q_dam[head]; head+=1
            p = df_map.get(curr)
            if p:
                if pd.notna(p[0]) and p[0] not in dam_ancestors: dam_ancestors.add(p[0]); q_dam.append(p[0])
                if pd.notna(p[1]) and p[1] not in dam_ancestors: dam_ancestors.add(p[1]); q_dam.append(p[1])
                
        common_ancestors = sire_ancestors.intersection(dam_ancestors)
        
        total_coancestry = 0.0
        for ancestor_id in common_ancestors:
            # For the ancestor's own inbreeding, use the fast tabular result for performance.
            ancestor_inbreeding = self.get_inbreeding_meuwissen(ancestor_id)
            
            # Find all paths from the sire and dam to this common ancestor.
            sire_paths = analyzer.find_all_paths_to_ancestor(df_map, sire_id, ancestor_id)
            dam_paths = analyzer.find_all_paths_to_ancestor(df_map, dam_id, ancestor_id)
            
            # Sum the contributions for each combination of paths.
            for n in sire_paths:
                for m in dam_paths:
                    total_coancestry += (0.5)**(n + m + 1) * (1 + ancestor_inbreeding)
        
        return total_coancestry