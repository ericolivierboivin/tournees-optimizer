import math

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import config


class SolverError(Exception):
    """Impossible de construire une tournée valide, peu importe l'heure de retour
    (ex : contraintes AM/PM incompatibles entre elles)."""


def _time_to_seconds(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 3600 + m * 60


def _build_and_solve(
    duration_matrix, stops, departure_secs, end_upper_bound, am_deadline_secs, pm_start_secs,
    pickup_before_delivery_penalty_seconds=0,
):
    n = len(duration_matrix)
    service_seconds = [0] + [s["service_seconds"] for s in stops]

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        cost = duration_matrix[i][j]
        if pickup_before_delivery_penalty_seconds and i > 0 and j > 0:
            # Pénalité douce : décourage (sans l'interdire) d'enchaîner une cueillette
            # suivie d'une livraison, pour favoriser le vidage du camion en premier.
            if stops[i - 1]["type"] == "cueillette" and stops[j - 1]["type"] == "livraison":
                cost += pickup_before_delivery_penalty_seconds
        return cost

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def time_callback(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return duration_matrix[i][j] + service_seconds[i]

    time_callback_index = routing.RegisterTransitCallback(time_callback)

    horizon = end_upper_bound + 1
    routing.AddDimension(
        time_callback_index,
        horizon,  # slack max : permet d'attendre qu'une fenêtre PM s'ouvre
        horizon,  # cumul max
        False,
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    for node in range(1, n):
        stop = stops[node - 1]
        index = manager.NodeToIndex(node)
        if stop["constraint"] == "am":
            time_dimension.CumulVar(index).SetRange(departure_secs, am_deadline_secs)
        elif stop["constraint"] == "pm":
            time_dimension.CumulVar(index).SetRange(pm_start_secs, end_upper_bound)
        else:
            time_dimension.CumulVar(index).SetRange(departure_secs, end_upper_bound)

    start_index = routing.Start(0)
    end_index = routing.End(0)
    time_dimension.CumulVar(start_index).SetRange(departure_secs, departure_secs)
    time_dimension.CumulVar(end_index).SetRange(departure_secs, end_upper_bound)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(10)

    solution = routing.SolveWithParameters(search_parameters)
    return manager, routing, time_dimension, solution


def solve_route(duration_matrix, stops, departure_time_str, pickup_before_delivery_penalty_seconds=0):
    """
    duration_matrix : matrice N x N de secondes (index 0 = dépôt).
    stops : liste (index 1..N-1) de dicts {'constraint': 'flexible'|'am'|'pm', 'service_seconds': int,
        'type': 'livraison'|'cueillette'}.
    departure_time_str : "HH:MM".
    pickup_before_delivery_penalty_seconds : pénalité douce (en secondes, ajoutée au coût de trajet
        mais pas aux heures réelles) quand une cueillette précède directement une livraison. 0 = désactivé.

    Retourne un dict avec l'ordre optimal, les heures d'arrivée/départ à chaque arrêt,
    l'heure de retour, et si la contrainte de 16h30 est respectée (avec le retard en minutes sinon).
    Lève SolverError si aucune tournée n'est possible peu importe l'heure de retour
    (typiquement un conflit AM/PM insoluble).
    """
    n = len(duration_matrix)
    if n != len(stops) + 1:
        raise ValueError("La matrice de trajet ne correspond pas au nombre d'arrêts.")

    departure_secs = _time_to_seconds(departure_time_str)
    closing_secs = _time_to_seconds(config.CLOSING_TIME)
    am_deadline_secs = _time_to_seconds(config.AM_DEADLINE)
    pm_start_secs = _time_to_seconds(config.PM_START)

    # Passe 1 : contrainte dure de fermeture à 16h30.
    manager, routing_model, time_dimension, solution = _build_and_solve(
        duration_matrix, stops, departure_secs, closing_secs, am_deadline_secs, pm_start_secs,
        pickup_before_delivery_penalty_seconds,
    )

    if solution is None:
        # Passe 2 : on relâche l'heure de retour pour estimer le retard réel (diagnostic).
        relaxed_upper = closing_secs + 6 * 3600
        manager, routing_model, time_dimension, solution = _build_and_solve(
            duration_matrix, stops, departure_secs, relaxed_upper, am_deadline_secs, pm_start_secs,
            pickup_before_delivery_penalty_seconds,
        )
        if solution is None:
            raise SolverError(
                "Impossible de construire une tournée respectant les contraintes horaires "
                "(probablement un conflit entre des arrêts AM et PM), peu importe l'heure de retour."
            )

    index = routing_model.Start(0)
    order = []
    arrival_seconds = {}
    departure_seconds = {}
    service_seconds = [0] + [s["service_seconds"] for s in stops]
    while True:
        node = manager.IndexToNode(index)
        order.append(node)
        arrival = solution.Value(time_dimension.CumulVar(index))
        arrival_seconds[node] = arrival
        departure_seconds[node] = arrival + service_seconds[node]
        if routing_model.IsEnd(index):
            break
        index = solution.Value(routing_model.NextVar(index))

    return_seconds = arrival_seconds[order[-1]]
    on_time = return_seconds <= closing_secs
    delay_minutes = 0 if on_time else math.ceil((return_seconds - closing_secs) / 60)

    return {
        "order": order,
        "arrival_seconds": arrival_seconds,
        "departure_seconds": departure_seconds,
        "return_seconds": return_seconds,
        "on_time": on_time,
        "delay_minutes": delay_minutes,
    }


def seconds_to_hhmm(seconds):
    seconds = int(seconds) % (24 * 3600)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h:02d}:{m:02d}"
