import pandas as pd
from .analysis import analyzer


class PedigreeCalculator:
    def __init__(self, df, progress_callback=None, core_animal_ids=None):
        """
        Initializes the calculator with a pedigree dataframe.
        The Meuwissen-Luo inbreeding coefficients are pre-calculated only on demand for large files.
        A cache is prepared for the traditional path-based calculation.

        Args:
            df: Pedigree dataframe
            progress_callback: Optional callable(current, total) for progress updates during IBC pre-calculation
            core_animal_ids: Optional list of core animal IDs to optimize Meuwissen calculation for
        """
        self.df = df.copy()
        self.core_animal_ids = core_animal_ids
        # The animal_id, sire_id, and dam_id are now string-based composite keys.
        # The numeric conversion is no longer needed and was causing errors.

        # Store progress callback for lazy Meuwissen-Luo calculation
        self.progress_callback = progress_callback

        # Lazy initialization: Meuwissen-Luo cache is created on-demand only if needed
        self.F_meuwissen_cache = None
        self.meuwissen_initialized = False

        # Initialize a cache for the slower path-based results to avoid re-computation
        self.F_path_cache = {}
    def _ensure_meuwissen_initialized(self):
        """Ensure Meuwissen-Luo cache is initialized (lazy initialization).
        Runs the optimized diagonal algorithm.
        """
        if not self.meuwissen_initialized:
            self.F_meuwissen_cache = analyzer.calculate_inbreeding_diagonal(
                self.df, progress_callback=self.progress_callback,
                core_animal_ids=self.core_animal_ids)
            self.meuwissen_initialized = True

    def get_inbreeding_meuwissen(self, animal_id):
        """
        Retrieves the pre-calculated Meuwissen-Luo inbreeding coefficient for an animal.
        Initializes the cache on first call if needed.
        """
        # The cache keys are now strings, so we ensure the input is a string.
        self._ensure_meuwissen_initialized()
        return self.F_meuwissen_cache.get(str(animal_id), 0.0)

    def get_inbreeding_traditional(self, animal_id):
        """
        Calculates the inbreeding coefficient for a single animal using the 
        traditional path-based algorithm. Caches results to speed up subsequent calls.
        """
        # It's critical that the F_path_cache is passed to and updated by the analyzer.
        return analyzer.calculate_inbreeding_path_based_for_animal(
            self.df, str(animal_id), self.F_path_cache
        )

    def calculate_coancestry(self, sire_id, dam_id):
        """
        Calculates the coancestry between a sire and a dam, which is equivalent
        to the inbreeding coefficient of their hypothetical offspring.

        For performance during mating simulations, this method uses the fast, 
        pre-calculated Meuwissen-Luo IBCs for the F-value of common ancestors.
        """
        # The sire_id and dam_id are now strings, so the int conversion is removed.
        sire_id, dam_id = str(sire_id), str(dam_id)

        # A map is needed for efficient path finding.
        df_map = {row.animal_id: (row.sire_id, row.dam_id)
                  for row in self.df.itertuples()}

        # Find all ancestors for both the sire and the dam to identify common ones.
        q_sire, q_dam = [sire_id], [dam_id]
        sire_ancestors, dam_ancestors = {sire_id}, {dam_id}

        head = 0
        while head < len(q_sire):
            curr = q_sire[head]
            head += 1
            p = df_map.get(curr)
            if p:
                if pd.notna(p[0]) and p[0] not in sire_ancestors:
                    sire_ancestors.add(p[0])
                    q_sire.append(p[0])
                if pd.notna(p[1]) and p[1] not in sire_ancestors:
                    sire_ancestors.add(p[1])
                    q_sire.append(p[1])

        head = 0
        while head < len(q_dam):
            curr = q_dam[head]
            head += 1
            p = df_map.get(curr)
            if p:
                if pd.notna(p[0]) and p[0] not in dam_ancestors:
                    dam_ancestors.add(p[0])
                    q_dam.append(p[0])
                if pd.notna(p[1]) and p[1] not in dam_ancestors:
                    dam_ancestors.add(p[1])
                    q_dam.append(p[1])

        common_ancestors = sire_ancestors.intersection(dam_ancestors)

        total_coancestry = 0.0
        for ancestor_id in common_ancestors:
            # For the ancestor's own inbreeding, use the fast tabular result for performance.
            ancestor_inbreeding = self.get_inbreeding_meuwissen(ancestor_id)

            # Find all paths from the sire and dam to this common ancestor.
            sire_paths = analyzer.find_all_paths_to_ancestor(
                df_map, sire_id, ancestor_id)
            dam_paths = analyzer.find_all_paths_to_ancestor(
                df_map, dam_id, ancestor_id)

            # Sum the contributions for each combination of paths.
            for n in sire_paths:
                for m in dam_paths:
                    total_coancestry += (0.5)**(n + m + 1) * \
                        (1 + ancestor_inbreeding)

        return total_coancestry
