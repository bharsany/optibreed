import sys
import pandas as pd

# Mock data
data = {
    'animal_id': ['1', '2', '3', '4', '5', '6'],
    'sire_id':   [None, None, '1', '1', '3', '5'],
    'dam_id':    [None, None, '2', '2', '4', '4']
}
df = pd.DataFrame(data)

df_map = {row.animal_id: (row.sire_id, row.dam_id) for row in df.itertuples()}

depth = {}
def get_depth(aid):
    if aid not in depth:
        depth[aid] = 0
        parents = df_map.get(aid)
        if parents:
            s, d = parents
            sd = get_depth(s) if pd.notna(s) else 0
            dd = get_depth(d) if pd.notna(d) else 0
            depth[aid] = max(sd, dd) + 1
        else:
            depth[aid] = 1
    return depth[aid]

for aid in df_map:
    get_depth(aid)

def get_inbreeding(a):
    if a == '5': return 0.25
    if a == '6': return 0.375 # f(5,4)
    return 0.0

def coancestry_recursive(a, b, memo=None):
    if memo is None: memo = {}
    if pd.isna(a) or pd.isna(b): return 0.0
    key = tuple(sorted([a,b]))
    if key in memo: return memo[key]
    
    if a == b:
        ans = 0.5 * (1.0 + get_inbreeding(a))
    else:
        d_a = depth.get(a, 0)
        d_b = depth.get(b, 0)
        if d_b > d_a:
            # Expand B
            p = df_map.get(b)
            if p and (pd.notna(p[0]) or pd.notna(p[1])):
                ans = 0.5 * (coancestry_recursive(a, p[0], memo) + coancestry_recursive(a, p[1], memo))
            else:
                ans = 0.0
        else:
            p = df_map.get(a)
            if p and (pd.notna(p[0]) or pd.notna(p[1])):
                ans = 0.5 * (coancestry_recursive(p[0], b, memo) + coancestry_recursive(p[1], b, memo))
            else:
                ans = 0.0
    memo[key] = ans
    return ans

print('f(3,4)=', coancestry_recursive('3', '4'))
print('f(5,4)=', coancestry_recursive('5', '4'))
print('f(5,6)=', coancestry_recursive('5', '6'))
