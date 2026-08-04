from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import config
import routing
import solver

TZ = ZoneInfo(config.TIMEZONE)

client = routing.get_client()

addresses = [
    config.DEPOT_ADDRESS,
    "2600 Boulevard Laurier, Québec, QC",
    "1000 Route de l'Église, Québec, QC",
    "999 Boulevard de Lévis, Lévis, QC",
    "1400 Boulevard Guillaume-Couture, Lévis, QC",
    "1100 Avenue Chouinard, Charny, QC",
    "500 Rue Racine, Charny, QC",
]
# Beaucoup de temps de service pour forcer un dépassement de 16h30.
stops_meta = [
    {"constraint": "am", "service_seconds": 90 * 60},
    {"constraint": "flexible", "service_seconds": 90 * 60},
    {"constraint": "pm", "service_seconds": 90 * 60},
    {"constraint": "flexible", "service_seconds": 90 * 60},
    {"constraint": "flexible", "service_seconds": 90 * 60},
    {"constraint": "pm", "service_seconds": 90 * 60},
]

locations = routing.geocode_addresses(client, addresses)
departure = datetime.now(TZ).replace(hour=8, minute=0, second=0, microsecond=0)
duration_matrix, distance_matrix = routing.build_time_matrix(client, locations, departure)

result = solver.solve_route(duration_matrix, stops_meta, "08:00")

print("On time :", result["on_time"], "| Retard (min) :", result["delay_minutes"])
print("Heure de retour estimee :", solver.seconds_to_hhmm(result["return_seconds"]))
print("Ordre :", result["order"])
