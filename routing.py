import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import googlemaps

import config

TZ = ZoneInfo(config.TIMEZONE)


class RoutingError(Exception):
    """Erreur lisible par l'agente (adresse introuvable, API indisponible, etc.)."""


ELEMENT_STATUS_HINTS = {
    "ZERO_RESULTS": (
        "Google ne trouve aucun itinéraire routier entre ces deux points. C'est presque "
        "toujours causé par une adresse incomplète ou imprécise (numéro civique manquant, "
        "type de rue omis — rue / boulevard / avenue / chemin —, ou mauvaise ville)."
    ),
    "NOT_FOUND": "Une des deux adresses n'a pas pu être localisée précisément par Google Maps.",
}

RESPONSE_STATUS_HINTS = {
    "OVER_QUERY_LIMIT": "La limite de requêtes Google a été atteinte. Réessayez dans quelques instants.",
    "REQUEST_DENIED": (
        "La clé API Google Maps n'est pas autorisée pour ce service. Vérifiez que la "
        "Distance Matrix API est bien activée et que la clé n'est pas restreinte de façon incompatible."
    ),
    "INVALID_REQUEST": "La requête envoyée à Google est invalide (problème technique interne à signaler).",
}

# Google peut « réussir » un géocodage même pour une adresse très vague, en la résolvant à
# l'échelle d'une ville, d'une province ou même du pays au complet. On exige au moins un de
# ces types, qui indique une correspondance à l'échelle d'une adresse ou d'une rue précise.
PRECISE_GEOCODE_TYPES = {
    "street_address",
    "premise",
    "subpremise",
    "route",
    "intersection",
    "establishment",
    "point_of_interest",
}


def _is_precise_geocode(result):
    return any(t in PRECISE_GEOCODE_TYPES for t in result.get("types", []))


def _describe_node(node_index, locations):
    loc = locations[node_index]
    if node_index == 0:
        return f"le point de départ (« {loc['formatted_address']} »)"
    return (
        f"l'arrêt {node_index} : « {loc['input']} » "
        f"(Google l'a compris comme « {loc['formatted_address']} »)"
    )


def get_client():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise RoutingError("Clé API Google Maps manquante (GOOGLE_MAPS_API_KEY).")
    return googlemaps.Client(key=api_key)


def geocode_addresses(client, addresses):
    """Géocode une liste d'adresses (addresses[0] = dépôt, les suivantes = arrêts 1..N dans
    l'ordre du formulaire). Retourne une liste de dicts dans le même ordre.
    Lève RoutingError avec le détail des arrêts en échec plutôt que d'en géocoder une partie."""
    results = []
    failed = []
    for idx, addr in enumerate(addresses):
        label = "le point de départ" if idx == 0 else f"l'arrêt {idx}"
        try:
            res = client.geocode(addr, region="ca", components={"country": "CA"})
        except Exception as exc:
            raise RoutingError(f"Erreur de géocodage pour {label} (« {addr} ») : {exc}") from exc
        if not res:
            failed.append(f"{label} (« {addr} »)")
            continue
        if not _is_precise_geocode(res[0]):
            failed.append(
                f"{label} (« {addr} ») — Google n'a trouvé qu'une correspondance approximative, "
                f"résolue comme « {res[0]['formatted_address']} » (trop vague pour être fiable)"
            )
            continue
        loc = res[0]["geometry"]["location"]
        results.append(
            {
                "input": addr,
                "lat": loc["lat"],
                "lng": loc["lng"],
                "formatted_address": res[0]["formatted_address"],
            }
        )
    if failed:
        raise RoutingError(
            "Adresse introuvable pour : " + " ; ".join(failed) + ".\n"
            "Vérifiez que l'adresse est complète : numéro civique, nom de la rue avec son type "
            "(rue, boulevard, avenue, chemin), et la ville. Exemple : "
            "1400 boulevard Guillaume-Couture, Lévis, QC."
        )
    return results


def _effective_departure_epoch(departure_dt):
    """La Distance Matrix API refuse un departure_time dans le passé."""
    now = datetime.now(TZ)
    safe_dt = max(departure_dt, now + timedelta(seconds=60))
    return int(safe_dt.timestamp())


def build_time_matrix(client, locations, departure_dt):
    """Construit la matrice N x N des temps de trajet réels (secondes, avec trafic) et des
    distances (mètres) entre tous les points (locations[0] = dépôt). Découpe les appels par
    blocs de 25 pour respecter la limite de la Distance Matrix API."""
    n = len(locations)
    coords = [f"{loc['lat']},{loc['lng']}" for loc in locations]
    duration_matrix = [[0] * n for _ in range(n)]
    distance_matrix = [[0] * n for _ in range(n)]

    epoch = _effective_departure_epoch(departure_dt)
    chunk = 25

    for i0 in range(0, n, chunk):
        origins_chunk = coords[i0 : i0 + chunk]
        for j0 in range(0, n, chunk):
            dest_chunk = coords[j0 : j0 + chunk]
            try:
                resp = client.distance_matrix(
                    origins=origins_chunk,
                    destinations=dest_chunk,
                    mode="driving",
                    departure_time=epoch,
                    traffic_model="best_guess",
                    units="metric",
                )
            except Exception as exc:
                raise RoutingError(f"Erreur Distance Matrix API : {exc}") from exc

            if resp.get("status") != "OK":
                status = resp.get("status")
                hint = RESPONSE_STATUS_HINTS.get(status, "")
                raise RoutingError(
                    f"Distance Matrix API a retourné le statut : {status}."
                    + (f"\n{hint}" if hint else "")
                )

            for oi, row in enumerate(resp["rows"]):
                for oj, elem in enumerate(row["elements"]):
                    if elem["status"] != "OK":
                        origin_desc = _describe_node(i0 + oi, locations)
                        dest_desc = _describe_node(j0 + oj, locations)
                        hint = ELEMENT_STATUS_HINTS.get(
                            elem["status"], f"Statut Google : {elem['status']}."
                        )
                        raise RoutingError(
                            f"Impossible de calculer le trajet entre {origin_desc} "
                            f"et {dest_desc}.\n{hint}"
                        )
                    duration = elem.get("duration_in_traffic", elem["duration"])["value"]
                    duration_matrix[i0 + oi][j0 + oj] = duration
                    distance_matrix[i0 + oi][j0 + oj] = elem["distance"]["value"]

    for i in range(n):
        duration_matrix[i][i] = 0
        distance_matrix[i][i] = 0

    return duration_matrix, distance_matrix


def maps_directions_link(ordered_addresses):
    """Construit un lien Google Maps multi-arrêts dans l'ordre donné (liste d'adresses formatées)."""
    if len(ordered_addresses) < 2:
        return None
    origin = ordered_addresses[0]
    destination = ordered_addresses[-1]
    waypoints = ordered_addresses[1:-1]
    from urllib.parse import quote

    params = f"api=1&origin={quote(origin)}&destination={quote(destination)}"
    if waypoints:
        waypoints_str = "|".join(quote(w) for w in waypoints)
        params += f"&waypoints={waypoints_str}"
    return f"https://www.google.com/maps/dir/?{params}"
