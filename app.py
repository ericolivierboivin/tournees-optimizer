import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for

load_dotenv()

import config
import routing
import solver

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)

APP_PASSWORD = os.environ.get("APP_PASSWORD")

TZ = ZoneInfo(config.TIMEZONE)

TYPE_LABELS = {
    "livraison": "Livraison",
    "cueillette": "Aller chercher / cueillette",
}
CONSTRAINT_LABELS = {
    "flexible": "Flexible",
    "am": "AM (avant 12h00)",
    "pm": "PM (après 13h00)",
}


@app.context_processor
def inject_defaults():
    return {"default_service_minutes": config.DEFAULT_SERVICE_MINUTES}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if APP_PASSWORD and not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session.permanent = True
            session["authenticated"] = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("login"))


def _parse_stops_from_form(form):
    adresses = form.getlist("adresse[]")
    types = form.getlist("type[]")
    contraintes = form.getlist("contrainte[]")
    temps_service = form.getlist("temps_service[]")

    stops_input = []
    for adresse, type_, contrainte, ts in zip(adresses, types, contraintes, temps_service):
        adresse = adresse.strip()
        if not adresse:
            continue
        try:
            service_minutes = int(ts) if ts.strip() else config.DEFAULT_SERVICE_MINUTES
        except ValueError:
            service_minutes = config.DEFAULT_SERVICE_MINUTES
        stops_input.append(
            {
                "adresse": adresse,
                "type": type_ if type_ in TYPE_LABELS else "livraison",
                "contrainte": contrainte if contrainte in CONSTRAINT_LABELS else "flexible",
                "service_minutes": max(0, service_minutes),
            }
        )
    return stops_input


@app.route("/", methods=["GET"])
@login_required
def index():
    return render_template(
        "index.html",
        default_departure=config.DEFAULT_DEPARTURE,
        stops=[],
        error=None,
        config_depot=config.DEPOT_ADDRESS,
    )


@app.route("/modifier", methods=["POST"])
@login_required
def modifier():
    """Renvoie au formulaire pré-rempli avec les arrêts déjà saisis, pour les ajuster
    (adresse, type, contrainte, temps de service) sans devoir tout retaper."""
    stops_input = _parse_stops_from_form(request.form)
    departure_time_str = request.form.get("heure_depart", "").strip() or config.DEFAULT_DEPARTURE
    return render_template(
        "index.html",
        default_departure=departure_time_str,
        stops=stops_input,
        error=None,
        config_depot=config.DEPOT_ADDRESS,
    )


@app.route("/optimiser", methods=["POST"])
@login_required
def optimiser():
    stops_input = _parse_stops_from_form(request.form)
    departure_time_str = request.form.get("heure_depart", "").strip() or config.DEFAULT_DEPARTURE

    if not stops_input:
        return render_template(
            "index.html",
            default_departure=departure_time_str,
            stops=[],
            error="Veuillez saisir au moins un arrêt.",
            config_depot=config.DEPOT_ADDRESS,
        )

    try:
        client = routing.get_client()
        addresses = [config.DEPOT_ADDRESS] + [s["adresse"] for s in stops_input]
        locations = routing.geocode_addresses(client, addresses)

        departure_dt = datetime.now(TZ).replace(
            hour=int(departure_time_str.split(":")[0]),
            minute=int(departure_time_str.split(":")[1]),
            second=0,
            microsecond=0,
        )
        duration_matrix, distance_matrix = routing.build_time_matrix(client, locations, departure_dt)

        solver_stops = [
            {"constraint": s["contrainte"], "service_seconds": s["service_minutes"] * 60}
            for s in stops_input
        ]
        result = solver.solve_route(duration_matrix, solver_stops, departure_time_str)
    except (routing.RoutingError, solver.SolverError) as exc:
        return render_template(
            "index.html",
            default_departure=departure_time_str,
            stops=stops_input,
            error=str(exc),
            config_depot=config.DEPOT_ADDRESS,
        )

    ordered_rows = []
    for node in result["order"]:
        if node == 0:
            continue
        stop = stops_input[node - 1]
        ordered_rows.append(
            {
                "adresse": locations[node]["formatted_address"],
                "type_label": TYPE_LABELS[stop["type"]],
                "contrainte_label": CONSTRAINT_LABELS[stop["contrainte"]],
                "arrivee": solver.seconds_to_hhmm(result["arrival_seconds"][node]),
                "depart": solver.seconds_to_hhmm(result["departure_seconds"][node]),
            }
        )

    ordered_addresses = [locations[node]["formatted_address"] for node in result["order"]]
    maps_link = routing.maps_directions_link(ordered_addresses)

    return render_template(
        "resultat.html",
        rows=ordered_rows,
        depot_address=locations[0]["formatted_address"],
        heure_depart=departure_time_str,
        heure_retour=solver.seconds_to_hhmm(result["return_seconds"]),
        on_time=result["on_time"],
        delay_minutes=result["delay_minutes"],
        maps_link=maps_link,
        closing_time=config.CLOSING_TIME,
        stops=stops_input,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050)
