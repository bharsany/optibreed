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
        self._ensure_meuwissen_initialized()
        aid = str(animal_id)
        if aid.endswith('.0'):
            aid = aid[:-2]
        return self.F_meuwissen_cache.get(aid, 0.0)

    def get_inbreeding_traditional(self, animal_id):
        """
        Calculates the inbreeding coefficient for a single animal using the 
        traditional path-based algorithm. Caches results to speed up subsequent calls.
        """
        aid = str(animal_id)
        if aid.endswith('.0'):
            aid = aid[:-2]
        if aid in self.F_path_cache:
            return self.F_path_cache[aid]
        df_map = self._get_df_map()
        return analyzer._calculate_inbreeding_for_animal_path_based(
            df_map, aid, self.F_path_cache
        )

    def _get_df_map(self):
        """Builds and caches the dictionary map for fast sire/dam lookup."""
        if not hasattr(self, '_df_map'):
            self._df_map = {}
            for row in self.df.itertuples():
                s = str(row.sire_id) if pd.notna(row.sire_id) else None
                d = str(row.dam_id) if pd.notna(row.dam_id) else None
                if s and s.endswith('.0'): s = s[:-2]
                if d and d.endswith('.0'): d = d[:-2]
                aid = str(row.animal_id)
                if aid.endswith('.0'): aid = aid[:-2]
                self._df_map[aid] = (s, d)
        return self._df_map

    def _get_ancestors_and_paths(self, animal_id, df_map):
        """
        Extracts all ancestors and calculates all paths to each ancestor from the given animal.
        Returns: {ancestor_id: [path_1, path_2, ...]} where path is a list of nodes.
        """
        # Dictionary to store list of paths to each ancestor
        paths_to = {}
        
        # Queue stores: (current_id, current_path)
        queue = [(animal_id, [])]
        head = 0
        
        while head < len(queue):
            curr, path = queue[head]
            head += 1
            
            new_path = path + [curr]
            if curr not in paths_to:
                paths_to[curr] = []
            paths_to[curr].append(new_path)
            
            parents = df_map.get(curr)
            if parents:
                sire, dam = parents
                if sire:
                    queue.append((sire, new_path))
                if dam:
                    queue.append((dam, new_path))
                    
        return paths_to

    def calculate_coancestry(self, sire_id, dam_id):
        """
        Calculates the coancestry between a sire and a dam, matching the EXACT
        mathematical output of the original path-based logic, but optimized heavily.
        """
        sire_id, dam_id = str(sire_id), str(dam_id)
        if sire_id.endswith('.0'): sire_id = sire_id[:-2]
        if dam_id.endswith('.0'): dam_id = dam_id[:-2]
        
        df_map = self._get_df_map()
        
        # 1. Get all ancestors and paths for sire
        sire_paths = self._get_ancestors_and_paths(sire_id, df_map)
        
        # 2. Get all ancestors and paths for dam
        dam_paths = self._get_ancestors_and_paths(dam_id, df_map)
        
        # 3. Find common ancestors
        common_ancestors = set(sire_paths.keys()).intersection(set(dam_paths.keys()))
        
        # 4. Calculate total path contributions correctly (no double counting)
        total_coancestry = 0.0
        for ancestor_id in common_ancestors:
            ancestor_inbreeding = self.get_inbreeding_meuwissen(ancestor_id)
            
            for s_path in sire_paths[ancestor_id]:
                for d_path in dam_paths[ancestor_id]:
                    # Only valid paths: intersection is exactly the common ancestor
                    if len(set(s_path).intersection(set(d_path))) == 1:
                        n = len(s_path) - 1
                        m = len(d_path) - 1
                        total_coancestry += (0.5)**(n + m + 1) * (1.0 + ancestor_inbreeding)
                        
        return total_coancestry
