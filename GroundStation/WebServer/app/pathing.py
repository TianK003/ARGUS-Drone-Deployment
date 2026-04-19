import math
import heapq
from collections import deque
from typing import List, Dict, Optional, Tuple, Set, Any

R_EARTH = 6378137

class Point:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

class Cell:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        
    def __eq__(self, other): return self.x == other.x and self.y == other.y
    def __hash__(self): return hash((self.x, self.y))
    def key(self): return f"{self.x}:{self.y}"

class Grid:
    def __init__(self, owner: List[List[Optional[str]]], x_min: float, y_min: float, cell: float, width: int, height: int, coverage: float):
        self.owner = owner
        self.x_min = x_min
        self.y_min = y_min
        self.cell = cell
        self.width = width
        self.height = height
        self.coverage_area = coverage

class DroneLocal:
    def __init__(self, id: str, x: float, y: float, r: float):
        self.id = id
        self.x = x
        self.y = y
        self.r = r

# ----------------- GEO MATH -----------------

def to_local(lat: float, lng: float, origin_lat: float, origin_lng: float) -> Point:
    d_lat = math.radians(lat - origin_lat)
    d_lng = math.radians(lng - origin_lng)
    x = d_lng * R_EARTH * math.cos(math.radians(origin_lat))
    y = d_lat * R_EARTH
    return Point(x, y)

def to_latlng(x: float, y: float, origin_lat: float, origin_lng: float) -> Tuple[float, float]:
    lat = origin_lat + math.degrees(y / R_EARTH)
    lng = origin_lng + math.degrees(x / (R_EARTH * math.cos(math.radians(origin_lat))))
    return lat, lng

# ----------------- PATHFINDING -----------------

path_cache: Dict[str, Any] = {}

def compute_paths(drones: List[Dict], stripe_spacing: int = 40, sweep_dir: str = 'ew') -> Dict[str, Any]:
    if not drones:
        return {"paths": {}, "coverage": 0}

    origin_lat = drones[0]['lat']
    origin_lng = drones[0]['lng']
    
    local = []
    for d in drones:
        p = to_local(d['lat'], d['lng'], origin_lat, origin_lng)
        local.append(DroneLocal(d['id'], p.x, p.y, d.get('reach', 800)))

    if sweep_dir == 'ns':
        rotated = [DroneLocal(d.id, d.y, d.x, d.r) for d in local]
    else:
        rotated = [DroneLocal(d.id, d.x, d.y, d.r) for d in local]

    grid = build_exclusive_grid(rotated, stripe_spacing)
    paths = {}

    for drone in rotated:
        route = build_drone_route_from_grid(grid, drone.id)
        ll_pts = []
        for pt in route:
            if sweep_dir == 'ns':
                unrot_x, unrot_y = pt.y, pt.x
            else:
                unrot_x, unrot_y = pt.x, pt.y
            lat, lng = to_latlng(unrot_x, unrot_y, origin_lat, origin_lng)
            ll_pts.append((lat, lng))
        paths[drone.id] = ll_pts

    return {"paths": paths, "coverage": grid.coverage_area}

def build_exclusive_grid(drones_local: List[DroneLocal], spacing: int) -> Grid:
    x_min, y_min = float('inf'), float('inf')
    x_max, y_max = float('-inf'), float('-inf')

    for d in drones_local:
        x_min = min(x_min, d.x - d.r)
        y_min = min(y_min, d.y - d.r)
        x_max = max(x_max, d.x + d.r)
        y_max = max(y_max, d.y + d.r)

    cell = max(10.0, float(spacing * 0.75))
    x_min -= cell
    y_min -= cell
    x_max += cell
    y_max += cell

    width = math.ceil((x_max - x_min) / cell)
    height = math.ceil((y_max - y_min) / cell)

    owner = [[None for _ in range(width)] for _ in range(height)]
    owned_count = 0

    for gy in range(height):
        y = y_min + (gy + 0.5) * cell
        for gx in range(width):
            x = x_min + (gx + 0.5) * cell
            owner_id = get_exclusive_owner(x, y, drones_local)
            owner[gy][gx] = owner_id
            if owner_id is not None:
                owned_count += 1

    path_cache.clear()
    
    return Grid(owner, x_min, y_min, cell, width, height, owned_count * cell * cell)

def get_exclusive_owner(x: float, y: float, drones_local: List[DroneLocal]) -> Optional[str]:
    best = None
    for d in drones_local:
        dx = x - d.x
        dy = y - d.y
        dist2 = dx*dx + dy*dy
        if dist2 > d.r * d.r:
            continue
            
        if not best or dist2 < best['dist2'] or \
          (dist2 == best['dist2'] and d.r < best['r']) or \
          (dist2 == best['dist2'] and d.r == best['r'] and str(d.id) < str(best['id'])):
            best = {'id': d.id, 'dist2': dist2, 'r': d.r}
            
    return best['id'] if best else None

def is_inside_grid(grid: Grid, x: int, y: int) -> bool:
    return 0 <= x < grid.width and 0 <= y < grid.height

def find_components(grid: Grid, drone_id: str) -> List[List[Cell]]:
    visited = [[False]*grid.width for _ in range(grid.height)]
    components = []
    dirs = [(1,0), (-1,0), (0,1), (0,-1)]

    for y in range(grid.height):
        for x in range(grid.width):
            if visited[y][x]: continue
            if grid.owner[y][x] != drone_id: continue

            q = deque([Cell(x, y)])
            comp = []
            visited[y][x] = True

            while q:
                cur = q.popleft()
                comp.append(cur)

                for dx, dy in dirs:
                    nx, ny = cur.x + dx, cur.y + dy
                    if is_inside_grid(grid, nx, ny) and not visited[ny][nx] and grid.owner[ny][nx] == drone_id:
                        visited[ny][nx] = True
                        q.append(Cell(nx, ny))
            
            components.append(comp)
            
    return components

def touches_foreign_or_empty(grid: Grid, drone_id: str, cell: Cell) -> bool:
    for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
        nx, ny = cell.x + dx, cell.y + dy
        if not is_inside_grid(grid, nx, ny): return True
        if grid.owner[ny][nx] != drone_id: return True
    return False

def component_boundary_cells(grid: Grid, drone_id: str, component: List[Cell]) -> List[Cell]:
    return [c for c in component if touches_foreign_or_empty(grid, drone_id, c)]

def cell_center_point(grid: Grid, cell: Cell) -> Point:
    p = Point(
        grid.x_min + (cell.x + 0.5) * grid.cell,
        grid.y_min + (cell.y + 0.5) * grid.cell
    )
    p.cell = cell
    return p

def contiguous_runs(xs: List[int]) -> List[Dict]:
    if not xs: return []
    runs = []
    start = xs[0]
    prev = xs[0]
    for x in xs[1:]:
        if x == prev + 1:
            prev = x
            continue
        runs.append({'start': start, 'end': prev})
        start = x
        prev = x
    runs.append({'start': start, 'end': prev})
    return runs

def simplify_points(points: List[Point]) -> List[Point]:
    if len(points) <= 2: return points[:]
    out = [points[0]]
    for i in range(1, len(points)-1):
        a = out[-1]
        b = points[i]
        c = points[i+1]
        cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)
        if abs(cross) < 1e-9: continue
        out.append(b)
    out.append(points[-1])
    return out

def manhattan(a: Cell, b: Cell) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

def seam_bias_cost(grid: Grid, drone_id: str, cell: Cell) -> int:
    foreign = empty = owned = 0
    for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
        nx, ny = cell.x + dx, cell.y + dy
        if not is_inside_grid(grid, nx, ny):
            empty += 1
            continue
        o = grid.owner[ny][nx]
        if o == drone_id: owned += 1
        elif o is None: empty += 1
        else: foreign += 1

    boundary = owned < 8
    cost = 2 if boundary else 28
    cost += owned * 2
    cost -= foreign * 2
    cost -= empty
    return max(1, cost)

def component_sweep_route(grid: Grid, drone_id: str, component: List[Cell]) -> List[Point]:
    cset = set(c.key() for c in component)
    rows = {}
    for c in component:
        rows.setdefault(c.y, []).append(c.x)

    ys = sorted(rows.keys())
    route = []

    for i, y in enumerate(ys):
        xs = sorted(rows[y])
        runs = contiguous_runs(xs)
        if i % 2 == 1: runs.reverse()

        for run in runs:
            seq = []
            if i % 2 == 0:
                for x in range(run['start'], run['end']+1):
                    if f"{x}:{y}" in cset: seq.append(Cell(x, y))
            else:
                for x in range(run['end'], run['start']-1, -1):
                    if f"{x}:{y}" in cset: seq.append(Cell(x, y))

            if not seq: continue
            points = [cell_center_point(grid, c) for c in seq]

            if not route:
                route.extend(points)
                continue

            from_cell = route[-1].cell
            to_cell = seq[0]

            connector = cheap_owned_connector(grid, drone_id, from_cell, to_cell)
            if not connector:
                connector = shortest_owned_cell_path(grid, drone_id, from_cell, to_cell)
            if connector and len(connector) > 1:
                route.extend(cell_center_point(grid, c) for c in connector[1:])
            route.extend(points)

    return simplify_points(route)

def reconstruct_path(prev_map: Dict[str, Cell], goal: Cell) -> List[Cell]:
    out = []
    cur = goal
    while cur:
        out.append(cur)
        cur = prev_map.get(cur.key())
    out.reverse()
    return out

def seam_hugging_owned_path(grid: Grid, drone_id: str, start: Cell, goal: Cell) -> Optional[List[Cell]]:
    start_key = start.key()
    goal_key = goal.key()
    heap = []
    heapq.heappush(heap, (manhattan(start, goal), 0, start))
    
    prev_map = {}
    g_score = {start_key: 0}
    closed = set()

    tiebreaker = 0
    while heap:
        f, _, current = heapq.heappop(heap)
        ckpt = current.key()
        if ckpt in closed: continue
        closed.add(ckpt)

        if ckpt == goal_key:
            return reconstruct_path(prev_map, current)

        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            nx, ny = current.x + dx, current.y + dy
            if not is_inside_grid(grid, nx, ny): continue
            if grid.owner[ny][nx] != drone_id: continue
            nk = f"{nx}:{ny}"
            if nk in closed: continue

            ncell = Cell(nx, ny)
            tentative = g_score.get(ckpt, float('inf')) + seam_bias_cost(grid, drone_id, ncell)
            if tentative < g_score.get(nk, float('inf')):
                prev_map[nk] = current
                g_score[nk] = tentative
                tiebreaker += 1
                heapq.heappush(heap, (tentative + manhattan(ncell, goal), tiebreaker, ncell))

    return None

def shortest_owned_cell_path(grid: Grid, drone_id: str, start: Cell, goal: Cell) -> Optional[List[Cell]]:
    a, b = start.key(), goal.key()
    cache_key = f"{drone_id}|{a}|{b}"
    if cache_key in path_cache: return path_cache[cache_key]

    rev_key = f"{drone_id}|{b}|{a}"
    if rev_key in path_cache:
        rev = path_cache[rev_key]
        ans = rev[::-1] if rev else None
        path_cache[cache_key] = ans
        return ans

    path = seam_hugging_owned_path(grid, drone_id, start, goal)
    path_cache[cache_key] = path
    return path

def cheap_owned_connector(grid: Grid, drone_id: str, start: Cell, goal: Cell) -> Optional[List[Cell]]:
    if start.x == goal.x:
        d = 1 if goal.y > start.y else -1
        path = [start]
        for y in range(start.y + d, goal.y + d, d):
            if not is_inside_grid(grid, start.x, y) or grid.owner[y][start.x] != drone_id:
                return None
            path.append(Cell(start.x, y))
        return path
    if start.y == goal.y:
        d = 1 if goal.x > start.x else -1
        path = [start]
        for x in range(start.x + d, goal.x + d, d):
            if not is_inside_grid(grid, x, start.y) or grid.owner[start.y][x] != drone_id:
                return None
            path.append(Cell(x, start.y))
        return path
    return None

def candidate_boundary_samples(grid: Grid, drone_id: str, info: Dict, use_end: bool) -> List[Dict]:
    route, boundary = info['route'], info['boundary']
    if not route or not boundary: return []
    anchor = route[-1].cell if use_end else route[0].cell

    scores = [(manhattan(c, anchor) + seam_bias_cost(grid, drone_id, c), c) for c in boundary]
    scores.sort(key=lambda x: x[0])
    best = [x[1] for x in scores[:6]]

    out = []
    for c in best: out.append({'cell': c, 'rev': False})
    for c in best: out.append({'cell': c, 'rev': True})
    return out

def build_drone_route_from_grid(grid: Grid, drone_id: str) -> List[Point]:
    components = find_components(grid, drone_id)
    if not components: return []

    route_infos = []
    for comp in components:
        route = component_sweep_route(grid, drone_id, comp)
        bnd = component_boundary_cells(grid, drone_id, comp)
        if route: route_infos.append({'comp': comp, 'route': route, 'boundary': bnd})
    
    if not route_infos: return []
    merged = route_infos.pop(0)

    while route_infos:
        best = None
        for i, cand in enumerate(route_infos):
            m_cands = candidate_boundary_samples(grid, drone_id, merged, True)
            o_cands = candidate_boundary_samples(grid, drone_id, cand, False)

            for a in m_cands:
                for b in o_cands:
                    s_cell = merged['route'][0].cell if a['rev'] else merged['route'][-1].cell
                    e_cell = cand['route'][-1].cell if b['rev'] else cand['route'][0].cell
                    c_path = shortest_owned_cell_path(grid, drone_id, s_cell, e_cell)
                    if not c_path or len(c_path) < 2: continue

                    cost = sum(seam_bias_cost(grid, drone_id, cp) for cp in c_path[1:])
                    if best is None or cost < best['cost']:
                        best = {'idx': i, 'm_rev': a['rev'], 'c_rev': b['rev'], 'cost': cost}

        if not best:
            fb = route_infos.pop(0)
            merged['route'] = simplify_points(merged['route'] + fb['route'])
            merged['boundary'] += fb['boundary']
            continue

        nxt = route_infos.pop(best['idx'])
        if best['m_rev']: merged['route'].reverse()
        if best['c_rev']: nxt['route'].reverse()

        s_cell = merged['route'][-1].cell
        g_cell = nxt['route'][0].cell

        conn = cheap_owned_connector(grid, drone_id, s_cell, g_cell)
        if not conn: conn = shortest_owned_cell_path(grid, drone_id, s_cell, g_cell)
        
        if conn and len(conn) > 1:
            cpts = [cell_center_point(grid, c) for c in conn[1:]]
            merged['route'] = simplify_points(merged['route'] + cpts + nxt['route'][1:])
        else:
            merged['route'] = simplify_points(merged['route'] + nxt['route'])
            
        merged['boundary'] += nxt['boundary']

    return merged['route']
