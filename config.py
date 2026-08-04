DEPOT_ADDRESS = "1269, rue Paul-Émile-Giroux, Beauport, QC, Canada"

OPENING_TIME = "08:00"
CLOSING_TIME = "16:30"
DEFAULT_DEPARTURE = "08:00"
DEFAULT_SERVICE_MINUTES = 30

AM_DEADLINE = "12:00"
PM_START = "13:00"

TIMEZONE = "America/Toronto"

# Pénalité douce (secondes) qui décourage d'enchaîner une cueillette suivie d'une livraison,
# pour favoriser le vidage du camion en premier. 0 = désactivé. Calibré à 15 min avec l'équipe
# le 2026-08-05 : assez pour forcer la préférence de façon fiable sans détour démesuré.
PICKUP_BEFORE_DELIVERY_PENALTY_SECONDS = 15 * 60
