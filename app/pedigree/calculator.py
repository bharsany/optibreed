import pandas as pd
from .analysis import analyzer

class PedigreeCalculator:
    def __init__(self, df):
        """
        Initializes the calculator with a pedigree dataframe.
        The Meuwissen-Luo inbreeding coefficients are pre-calculated for speed.
        """
        self.df = df.copy()
        self.df['animal_id'] = pd.to_numeric(self.df['animal_id'], errors='coerce').astype(int)
        for col in ['sire_id', 'dam_id']:
            self.df[col] = pd.to_numeric(self.df[col], errors='coerce').astype('Int64')
        
        self.F_meuwissen_cache = analyzer.calculate_inbreeding_tabular(self.df)

    def get_inbreeding_meuwissen(self, animal_id):
        """
        Retrieves the pre-calculated Meuwissen-Luo inbreeding coefficient.
        """
        return self.F_meuwissen_cache.get(animal_id, 0.0)

    def get_inbreeding_traditional(self, animal_id):
        """
        For simplicity and performance, this now returns the fast Meuwissen-Luo result.
        """
        return self.get_inbreeding_meuwissen(animal_id)

    def calculate_coancestry(self, sire_id, dam_id):
        """
        Calculates the coancestry between a sire and a dam using the path-based method, 
        but optimized to use the fast, pre-calculated inbreeding coefficients.
        """
        sire_id, dam_id = int(sire_id), int(dam_id)
        sire_ancestors = analyzer.get_ancestors_path_based(self.df, sire_id)
        dam_ancestors = analyzer.get_ancestors_path_based(self.df, dam_id)
        common_ancestors = sire_ancestors.intersection(dam_ancestors)
        
        total_coancestry = 0.0
        for ancestor_id in common_ancestors:
            ancestor_id = int(ancestor_id)
            
            # Use the fast, pre-calculated inbreeding coefficient for the ancestor.
            ancestor_inbreeding = self.get_inbreeding_meuwissen(ancestor_id)

            sire_paths = analyzer.find_all_paths_path_based(self.df, sire_id, ancestor_id)
            dam_paths = analyzer.find_all_paths_path_based(self.df, dam_id, ancestor_id)

            path_contribution_sum = 0
            for n in sire_paths:
                for m in dam_paths:
                    path_contribution_sum += (0.5)**(n + m + 1)
            
            total_coancestry += path_contribution_sum * (1 + ancestor_inbreeding)
            
        return total_coancestry
