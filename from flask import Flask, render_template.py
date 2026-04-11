from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import random
import networkx as nx
import math
import time

from graph_data import CITIES, ROUTES

app = Flask(__name__)
CORS(app)

# Build NetworkX Graph
G = nx.DiGraph()
for city in CITIES:
    G.add_node(city["id"], name=city["name"], lat=city["lat"], lng=city["lng"])

for u, neighbors in ROUTES.items():
    for v, data in neighbors.items():
        dist = data["dist"]
        cap = data["cap"]
        route_name = data["name"]
        
        # Simulate initial traffic multiplier (1.0 = clear, 2.5 = very slow)
        traffic_multiplier = random.uniform(1.0, 2.5)
        fuel_cost = dist * 0.15 
        speed_limit = data.get("speed_limit", 80)
        
        G.add_edge(u, v, weight=dist * traffic_multiplier, distance=dist, capacity=cap, fuel=fuel_cost, route_name=route_name, traffic=traffic_multiplier, speed_limit=speed_limit)

# Build an undirected version for some algorithms
G_undirected = G.to_undirected()


def generate_directions(path, graph, mode='normal'):
    directions = []
    total_distance = 0
    total_time_mins = 0
    
    # Multipliers to ensure hierarchy:
    # EMERGENCY > SHORTEST > NORMAL > PEAK
    # We use route-specific speed limits (e.g. 120 for expressways, 80 for NH)
    config = {
        'emergency': {'mult': 1.2, 'penalty': 0.1}, # Exceed limit if allowed? or just close to it
        'shortest': {'mult': 1.0, 'penalty': 0.3},
        'normal': {'mult': 0.85, 'penalty': 1.0},
        'peak': {'mult': 0.6, 'penalty': 2.5}
    }
    
    m_cfg = config.get(mode, config['normal'])
    
    for i in range(len(path) - 1):
        u = path[i]
        v = path[i+1]
        edge_data = graph[u][v]
        dist = edge_data['distance']
        traffic = edge_data['traffic']
        limit = edge_data['speed_limit']
        
        total_distance += dist
        
        # Base speed for this road type adjusted by mode
        base_speed = limit * m_cfg['mult']
        
        # Effective speed calculation with traffic penalty
        effective_speed = base_speed / (1 + (traffic - 1) * m_cfg['penalty'])
        effective_speed = max(effective_speed, 10) # Floor at 10km/h
        
        total_time_mins += (dist / effective_speed) * 60
        
        directions.append({
            "instruction": f"Take {edge_data['route_name']} towards {next(c['name'] for c in CITIES if c['id'] == v)}",
            "distance": round(dist, 1)
        })
        
    directions.append({
        "instruction": f"Arrive at destination: {next(c for c in CITIES if c['id'] == path[-1])['name']}"
    })
    return directions, total_distance, int(total_time_mins)


@app.route('/')
def index():
    graph_stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": round(nx.density(G), 3),
        "avg_degree": round(sum(dict(G.degree()).values()) / G.number_of_nodes(), 1)
    }
    return render_template('index.html', cities=CITIES, graph_stats=graph_stats)


@app.route('/api/weather/<city_id>')
def get_weather(city_id):
    # Stabilized weather: use city_id to seed the random number
    # This ensures "Delhi" always has the same temp during a session, rather than changing on every click.
    seed_val = sum(ord(c) for c in city_id)
    r = random.Random(seed_val)
    
    return jsonify({
        "temperature": r.randint(22, 38),
        "condition": r.choice(["Sunny", "Cloudy", "Clear"]),
        "aqi": r.randint(60, 320),
        "wind_speed": r.randint(5, 20),
        "humidity": r.randint(40, 70)
    })

@app.route('/api/cities')
def list_cities():
    """Return basic city data for populating dropdowns on the frontend."""
    return jsonify([
        {"id": c["id"], "name": c["name"], "lat": c["lat"], "lng": c["lng"]}
        for c in CITIES
    ])

@app.route('/api/route', methods=['POST'])
def calculate_route():
    start_time = time.time()
    data = request.json
    start = data.get('start')
    end = data.get('end')
    mode = data.get('mode', 'normal') 
    scenario = data.get('scenario', 'none')
    avoid_tolls = data.get('avoid_tolls', False)
    avoid_highways = data.get('avoid_highways', False)
    
    if not start or not end or not G.has_node(start) or not G.has_node(end):
        return jsonify({"error": "Invalid start or end location"}), 400
        
    try:
        # Penalize Tolls or Highways if requested
        penalty_graph = G.copy()
        for u, v, d in penalty_graph.edges(data=True):
            mult = 1.0
            if avoid_tolls and "Expressway" in d.get("route_name", ""):
                mult *= 20.0 # Huge penalty
            if avoid_highways and ("NH" in d.get("route_name", "") or "Expressway" in d.get("route_name", "")):
                mult *= 15.0
            d['penalty_weight'] = d['weight'] * mult

        if mode == 'emergency' or mode == 'shortest':
            path = nx.shortest_path(penalty_graph, source=start, target=end, weight='distance')
        elif mode == 'peak':
            for u, v, dat in penalty_graph.edges(data=True):
                dat['peak_weight'] = dat['distance'] * (dat['traffic'] ** 2) * (dat['weight'] / dat['distance']) # keep avoid penalties
            path = nx.shortest_path(penalty_graph, source=start, target=end, weight='peak_weight')
        else:
            path = nx.shortest_path(penalty_graph, source=start, target=end, weight='penalty_weight')
            
        directions, total_distance, total_time = generate_directions(path, G, mode=mode)
        path_coords = [{"lat": G.nodes[node]["lat"], "lng": G.nodes[node]["lng"]} for node in path]
        
        # Calculate Transport Variations
        modes_data = {
            "car": {"time": total_time},
            "bike": {"time": int(total_time * 0.8)},
            "train": {"time": int((total_distance / 40) * 60) + 30}, # Simulating slow train with stops
            "walk": {"time": int((total_distance / 5) * 60)}
        }
        
        segments = []
        gas_stations = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            data = G[u][v]
            traffic_val = data['traffic']
            color = "#10b981"
            if traffic_val > 2.2: color = "#ef4444"
            elif traffic_val > 1.5: color = "#f59e0b"
            
            if random.random() > 0.4:
                rand_fraction = random.uniform(0.1, 0.9)
                lat = G.nodes[u]["lat"] + rand_fraction * (G.nodes[v]["lat"] - G.nodes[u]["lat"])
                lng = G.nodes[u]["lng"] + rand_fraction * (G.nodes[v]["lng"] - G.nodes[u]["lng"])
                gas_stations.append({
                    "lat": round(lat, 5), "lng": round(lng, 5),
                    "prices": {"petrol": 98.4, "diesel": 89.2, "cng": 75.0},
                    "brand": random.choice(["IndianOil", "HP", "Jio-bp"])
                })
            segments.append({"from": [G.nodes[u]["lat"], G.nodes[u]["lng"]], "to": [G.nodes[v]["lat"], G.nodes[v]["lng"]], "color": color})
        
        calc_time = round(time.time() - start_time, 4)
        avg_mileage, avg_fuel_price = 5.0, 92.5
        est_cost = (total_distance / avg_mileage) * avg_fuel_price
        carbon_emission = total_distance * 0.82
        
        return jsonify({
            "path": path, "coordinates": path_coords, "segments": segments, "gas_stations": gas_stations,
            "distance": round(total_distance, 2), "estimated_cost": int(est_cost),
            "carbon_emission": round(carbon_emission, 1), "directions": directions,
            "estimated_time_mins": total_time, "calc_time_ms": int(calc_time * 1000),
            "modes_data": modes_data
        })
    except nx.NetworkXNoPath:
        return jsonify({"error": "No route possible."}), 404

@app.route('/api/traffic/refresh', methods=['POST'])
def refresh_traffic():
    # Simulate a "Live Update" from road sensors
    for u, v, dat in G.edges(data=True):
        dat['traffic'] = random.uniform(1.0, 3.0)
        dat['weight'] = dat['distance'] * dat['traffic']
    return jsonify({"status": "Live traffic data synchronized from 500+ sensors."})

@app.route('/api/traffic')
def get_traffic():
    traffic_data = []
    # Fetch live traffic data across the whole network to draw on map!
    for u, v, data in G.edges(data=True):
        # Determine color/level based on traffic multiplier (1.0 to 3.0)
        traffic_level = "green"
        if data['traffic'] > 2.2:
            traffic_level = "red"
        elif data['traffic'] > 1.5:
            traffic_level = "orange"
            
        traffic_data.append({
            "from": {"lat": G.nodes[u]["lat"], "lng": G.nodes[u]["lng"]},
            "to": {"lat": G.nodes[v]["lat"], "lng": G.nodes[v]["lng"]},
            "level": traffic_level,
            "route_name": data['route_name']
        })
    return jsonify(traffic_data)


# ------------- ADVANCED NETWORK ANALYTICS API -------------

@app.route('/api/analytics/centrality')
def get_centrality():
    bc = nx.betweenness_centrality(G_undirected, weight='distance')
    cc = nx.closeness_centrality(G_undirected, distance='distance')
    sorted_bc = sorted(bc.items(), key=lambda item: item[1], reverse=True)
    
    results = {
        "betweenness": [{"city": k, "score": round(v, 4)} for k, v in sorted_bc],
        "closeness": [{"city": k, "score": round(v, 4)} for k, v in cc.items()]
    }
    
    top_hub = sorted_bc[0][0] if sorted_bc else None
    results["top_hub"] = top_hub
    results["top_hub_name"] = next((c["name"] for c in CITIES if c["id"] == top_hub), "None")
    
    return jsonify(results)

@app.route('/api/analytics/bottleneck', methods=['POST'])
def get_bottleneck():
    data = request.json
    start = data.get('source')
    end = data.get('sink')
    
    if not start or not end or not G.has_node(start) or not G.has_node(end):
        return jsonify({"error": "Invalid source or sink"}), 400
        
    try:
        cut_value, partition = nx.minimum_cut(G, start, end, capacity='capacity')
        reachable, non_reachable = partition
        
        cut_set = set()
        for u, nbrs in ((n, G[n]) for n in reachable):
            cut_set.update((u, v) for v in nbrs if v in non_reachable)
            
        bottlenecks = []
        for u, v in cut_set:
            bottlenecks.append({
                "from": G.nodes[u]["name"],
                "to": G.nodes[v]["name"],
                "capacity": G[u][v]["capacity"]
            })
            
        return jsonify({
            "max_flow": cut_value,
            "bottleneck_segments": bottlenecks,
            "reachable_cities": list(reachable)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analytics/tsp')
def get_tsp():
    try:
        path = nx.approximation.traveling_salesman_problem(G_undirected, weight='distance')
        directions, total_distance, total_time = generate_directions(path, G_undirected)
        path_coords = [{"lat": G.nodes[node]["lat"], "lng": G.nodes[node]["lng"]} for node in path]
        
        return jsonify({
            "path": path,
            "coordinates": path_coords,
            "distance": round(total_distance, 2)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
