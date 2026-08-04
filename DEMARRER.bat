@echo off
cd /d "%~dp0"
echo Demarrage de l'optimiseur de tournees...
echo Une fois demarre, ouvrez votre navigateur a l'adresse : http://localhost:5050
start "" http://localhost:5050
venv\Scripts\python.exe app.py
pause
