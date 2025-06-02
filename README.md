# Routing component of Mobility platform

In dieser Datei soll skizziert werden, wie die Entwicklung des Routing-Service abläuft.

## Inhaltsverzeichnis

  - [Algemeine Informationen](#algemeine-informationen)
  - [Allgemeine Infos zu Entwicklungstools](#allgemeine-infos-zu-entwicklungstools)
    - [GitHub-Repo](#github-repo)
    - [Algorithmen-Entwicklung in Python](#algorithmen-entwicklung-in-python)
  - [Entwickeln und Debuggen](#entwickeln-und-debuggen)
    - [Docker aufräumen](#docker-aufräumen)
    - [Docker-Container bauen und starten](#docker-container-bauen-und-starten)
    - [Die einzelnen Docker-Container und ihre Bedeutung](#die-einzelnen-docker-container-und-ihre-bedeutung)
  - [ORTools](#ortools)
    - [Das TSP-Problem wird vom Solver als INTEGER-Optimierung angesehen](#das-tsp-problem-wird-vom-solver-als-integer-optimierung-angesehen)


## Algemeine Informationen

Das Routing ist Teil des Backends und zuständig für die Berechnung und Otpimierung von Routen. Die eigentliche Datenverwaltung findet in einem anderen Service des Backend (Order-Service - Directus) statt.

## Allgemeine Infos zu Entwicklungstools

### GitHub-Repo

Der Quellcode für das Routing ist in diesem GitHub-Projekt abgelegt.

* Achtung: die Karten-Daten im Ordner `Maps` sind im GIT-LFS (Large-FileStorage), man muss sichergehen, dass die Daten heruntergeladen wurden. Workaround: Daten manuell aus GitHub downloaden

### Algorithmen-Entwicklung in Python

Der Routing-Algorithmus ist in Python programmiert. Für die Lösung des Optimierungsproblems wird der Paket `ORTools` von Google genutzt. Die Python-Entwicklung kann zum Beispiel in `Visual Studio Code` oder mit `PyCharm` erfolgen. Alle genutzen Python-Packages sind in `requirements.txt` aufgelistet.

Als Online-Routingservice wurde mit `OSRM` experimentiert, teilweise können die Algorithmen auf `ORSM` zugreifen. Dafür kann man entweder den öffentlichen `OSRM`-Testserver nutzen (langsam!) oder man baut sich eine eigene Instanz (performanter!).

Die Datenbankentwicklung erfolgt mit dem Python-basierten Framework `Django`. Als Messaging-Service wird `RabbitMQ` verwendet. Als Datenbank fungiert `PostgreSQL`.

Für nebenläufige Tasks (z.B. Wartungsaufgaben im Routing-Backend) werden `celery-beat` und `celery-worker` genutzt.

**Routing**

Der Quellcode für den Routing-Kernalgorithmus liegt im Ordner `routing`. Der Code ist mit einer lokalen Python-Installation ausführbar.

**Routing Datenbank-Service und API**

Die API, Datenbankstruktur und Migrations werden mit `Django` in Quellcode modelliert. Den Code findet man im Ordner `Routing_Api`.

## Entwickeln und Debuggen

Für die Python-Entwicklung wird Wissen vorausgesetzt und hier nicht näher erläutert. Wichtig für die Entwicklung ist das Verständnis, dass API- und Datenbank-Funktionen nur im Zusammenspiel mit Datenbank-Services und Messegaging-Services funktionieren. Die notwendigen Services werden als Docker-Container aufgebaut. Für die Verwendung ist die Installation von `Docker-Desktop` notwendig.

Im Folgenden werden einzelne Arbeitsschritte mit Docker angerissen, die für Anwender mit wenig Vorwissen zum Einstieg ins Thema geeignet sein können. Versierte Docker-Anwender werden zum Teil bessere Lösungen kennen, wir empfehlen eine intensive Einarbeitung in Docker.

### Docker aufräumen
* alle Container wegräumen 
```
docker-compose down
```
* alle Volumes aufräumen
```
 docker volume rm $(docker volume ls -q)
 ```

### Docker-Container bauen und starten
* im Firmen-Netz braucht man evtl. die Umgebungsvariablen bzw. Proxyeinstellungen und Windows (beim Zugang mit AnyConnect ggfs AnyConnect trennen): 
```
HTTP_PROXY='your_prox_path:00'
HTTPS_PROXY='your_prox_path:00'
NO_PROXY='your_ignore_list'
```

In der Powershell kann man die Umgebungsvariablen so setzen:
```
$env:HTTP_PROXY='your_prox_path:00'
$env:HTTPS_PROXY='your_prox_path:00'
$env:NO_PROXY='your_ignore_list'
get-childitem env:* # Anzeigen der Umgebungsvariablen
```

**In Docker Desktop die Proxies ausschalten, wenn man nicht im Firmen-Netz ist! Gegebenenfalls Docker neu starten.**

* Docker starten (Hinweis: mit Docker-Einstellung "WSL2" eventuell deutlich schneller beim Starten, dafür scheint die Gefahr, dass DirectAccess wegbricht, höher zu sein)
* Container bauen und starten
* bei Zugang zum Firmen-Netz über VPN-Client funktioniert das Compose evtl. nicht; Lösung: Verbindung trennen
* häufiger sind mehrfache Versuche nötig, um den Container zu bauen; eventuell Docker schließen und neu starten oder alle Container löschen und neu bauen
```
 docker-compose up -d --build # alles
```
* Stand 11/2021: ein Port wird mehrfach genutzt und deshalb lassen sich nicht alle Container starten, kann man erstmal ignorieren (ggfs. "Adminer" stoppen) bzw Portnummern anpassen

### Die einzelnen Docker-Container und ihre Bedeutung

**Web-Container**
```
docker-compose up -d --build web
```
Mit diesem Container hat man einen lokalen Routing-Server um die Api etc. zu testen. Aufruf beginnen mit `localhost:portnummer`, zum Beispiel:
```
http://localhost:8080/routes/?startLatitude=50.684529404859774&startLongitude=12.80551264237144&stopLatitude=50.64192430537674&stopLongitude=12.81952450226538&time=2022-01-21T11%3A30%3A00%2B01%3A00&isDeparture=true&seatNumber=1&seatNumberWheelchair=0&routeId=0&routeId=0&suggestAlternatives=later
```
Damit dieser Container richtig arbeiten könnte, müsste aber lokal auch das Backend zur Verfügung gestellt werden. Ansonsten sind die Testmöglichkeiten beschränkt. Es ist möglich, das Directus-Backend anzuschließen.

**RabbitMQ**

Dieser Container liefert den Broker für die Event-Kommunikation.

**Celery-Beat und Celery-Worker**
```
docker-compose up -d --build celery-beat
docker-compose up -d --build celery-worker
```
Hiermit werden die nebenläufigen Tasks gestartet, siehe tasks.py.

## ORTools 
### Das TSP-Problem wird vom Solver als INTEGER-Optimierung angesehen
Wichtig zu wissen: https://developers.google.com/optimization/cp/cp_solver
Das heißt: alle Inputs für den Optimierer sind als Integer anzusehen. In der aktuellen Implementierung sind:
- Zeiten in Minuten: kleinste Einheit ist eine Minute
- Entfernungen: nicht im Optimierer berücksichtigt (wird alles über Zeiten gemacht)