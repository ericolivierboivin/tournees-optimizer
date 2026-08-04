from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import config
import routing
import solver

TZ = ZoneInfo(config.TIMEZONE)

client = routing.get_client()

# Dépôt + 4 arrêts réalistes (Rive-Nord et Rive-Sud), avec contraintes variées.
addresses = [
    config.DEPOT_ADDRESS,
    "2600 Boulevard Laurier, Québec, QC",       # Rive-Nord (Sainte-Foy)
    "1000 Route de l'Église, Québec, QC",       # Rive-Nord
    "999 Boulevard de Lévis, Lévis, QC",         # Rive-Sud
    "1400 Boulevard Guillaume-Couture, Lévis, QC",  # Rive-Sud
]
stops_meta = [
    {"constraint": "am", "service_seconds": 30 * 60},       # doit être avant midi
    {"constraint": "flexible", "service_seconds": 20 * 60},
    {"constraint": "pm", "service_seconds": 45 * 60},        # doit être après 13h
    {"constraint": "flexible", "service_seconds": 30 * 60},
]

locations = routing.geocode_addresses(client, addresses)
departure = datetime.now(TZ).replace(hour=8, minute=0, second=0, microsecond=0)
duration_matrix, distance_matrix = routing.build_time_matrix(client, locations, departure)

result = solver.solve_route(duration_matrix, stops_meta, "08:00")

print("Ordre (indices) :", result["order"])
print("On time :", result["on_time"], "| Retard (min) :", result["delay_minutes"])
print()
for node in result["order"]:
    label = "DEPOT" if node == 0 else f"Arret {node} ({addresses[node]})"
    arr = solver.seconds_to_hhmm(result["arrival_seconds"][node])
    dep = solver.seconds_to_hhmm(result["departure_seconds"][node])
    print(f"{label:60s} arrivee={arr} depart={dep}")
