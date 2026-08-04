from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import config
import routing

TZ = ZoneInfo(config.TIMEZONE)

client = routing.get_client()

addresses = [
    config.DEPOT_ADDRESS,
    "2600 Boulevard Laurier, Québec, QC",  # Sainte-Foy (Rive-Nord)
    "1000 Route de l'Église, Québec, QC",  # Rive-Nord
    "999 Boulevard de Lévis, Lévis, QC",  # Rive-Sud
]

locations = routing.geocode_addresses(client, addresses)
for loc in locations:
    print(loc["input"], "->", loc["formatted_address"], loc["lat"], loc["lng"])

departure = datetime.now(TZ).replace(hour=8, minute=0, second=0, microsecond=0)
duration_matrix, distance_matrix = routing.build_time_matrix(client, locations, departure)

print("\nMatrice de durées (secondes) :")
for row in duration_matrix:
    print(row)

print("\nLien Google Maps :")
print(routing.maps_directions_link([loc["formatted_address"] for loc in locations]))
