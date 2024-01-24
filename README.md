[![Unit tests](https://github.com/Smoothex/erzmobil-routing/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/Smoothex/erzmobil-routing/actions/workflows/unit-tests.yml)
[![Integration tests](https://github.com/Smoothex/erzmobil-routing/actions/workflows/integration-tests.yml/badge.svg)](https://github.com/Smoothex/erzmobil-routing/actions/workflows/integration-tests.yml)
[![Build and push image to AWS ECR](https://github.com/Smoothex/erzmobil-routing/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/Smoothex/erzmobil-routing/actions/workflows/build-and-push.yml)

# bUSnow-routing

In dieser Datei soll skizziert werden, wie die Entwicklung des Routing-Service abläuft (Stand 07/2023).

## Inhaltsverzeichnis

  - [Algemeine Informationen](#algemeine-informationen)
  - [Allgemeine Infos zu Entwicklungstools](#allgemeine-infos-zu-entwicklungstools)
    - [GitHub-Repo](#github-repo)
    - [GitHub Actions](#github-actions)
    - [Algorithmen-Entwicklung in Python](#algorithmen-entwicklung-in-python)
  - [Entwickeln und Debuggen](#entwickeln-und-debuggen)
    - [Docker aufräumen](#docker-aufräumen)
    - [Docker-Container bauen und starten](#docker-container-bauen-und-starten)
    - [Die einzelnen Docker-Container und ihre Bedeutung](#die-einzelnen-docker-container-und-ihre-bedeutung)
    - [Integrationstests](#integrationstests)
    - [Lokales Entwicklen, Debuggen und Unit-Tests](#lokales-entwicklen-debuggen-und-unit-tests)
    - [Code Coverage beim Testen ermitteln](#code-coverage-beim-testen-ermitteln)
    - [Profilen der Unittests](#profilen-der-unittests)
    - [Debuggen der Integrationstests im Docker-Container "tester"](#debuggen-der-integrationstests-im-docker-container-tester)
    - [Debuggen des routing-service in aws pod](#debuggen-des-routing-service-in-aws-pod)
  - [Django-Migrations erstellen, wenn Models angepasst wurden](#django-migrations-erstellen-wenn-models-angepasst-wurden)
  - [ORTools](#ortools)
    - [Das TSP-Problem wird vom Solver als INTEGER-Optimierung angesehen](#das-tsp-problem-wird-vom-solver-als-integer-optimierung-angesehen)
  - [OSRM Routing](#osrm-routing)
    - [OSRM aktivieren per Env-Variable](#osrm-aktivieren-per-env-variable)


## Algemeine Informationen

Das Routing ist Teil des Backends und zuständig für die Berechnung und Otpimierung von Routen. Die eigentliche Datenverwaltung findet in einem anderen Service des Backend (Order-Service - Directus) statt.

## Allgemeine Infos zu Entwicklungstools

### GitHub-Repo

Der Quellcode für das Routing ist in diesem GitHub-Projekt abgelegt.

* Achtung: die Karten-Daten im Ordner `Maps` sind im GIT-LFS (Large-FileStorage), man muss sichergehen, dass die Daten heruntergeladen wurden, ansonsten können die Tests nicht funktionieren, Workaround: Daten manuell aus GitHub downloaden

### GitHub Actions

Es wurde eine GitHub Actions Pipeline aufgebaut, die:

- bei jedem Commit alle Tests durchlaufen lässt
- bei jedem Merge in den Hauptzweig die neuen Images fürs Routing baut

> **Hinweis**:
>
> Die Pipeline kann auch den Deploy ins Produktivsystem automatisieren. Hier ist die Frage, ob man das will. Stand 07/2023 ist diese Funktion nicht funktionsfähig und nicht gewollt.

> **Hinweis**:
>
> Die Integrationstest sind teilweis sehr instabil, weil asynchrone API-Aufrufe drin sind und die Antwortzeiten unter Umständen sehr stark variieren. Es ist dann ein Erweitern von Timeouts/Wartezeiten ratsam. OSRM-Tests können ebenfalls in der Perfomance stark variieren oder (aufgrund angepasster Online-Karten) abweichende Testergebnisse liefern.

### Algorithmen-Entwicklung in Python

Der Routing-Algorithmus ist in Python programmiert. Für die Lösung des Optimierungsproblems wird der Paket `ORTools` von Google genutzt. Die Python-Entwicklung kann zum Beispiel in `Visual Studio Code` oder mit `PyCharm` erfolgen. Alle genutzen Python-Packages sind in `requirements.txt` aufgelistet.

Als Online-Routingservice wurde mit `OSRM` experimentiert, teilweise können die Algorithmen auf `ORSM` zugreifen. Dafür kann man entweder den öffentlichen `OSRM`-Testserver nutzen (langsam!) oder man baut sich eine eigene Instanz (performanter!).

Die Datenbankentwicklung erfolgt mit dem Python-basierten Framework `Django`. Als Messaging-Service wird `RabbitMQ` verwendet. Als Datenbank fungiert `PostgreSQL`.

Für nebenläufige Tasks (z.B. Wartungsaufgaben im Routing-Backend) werden `celery-beat` und `celery-worker` genutzt.

Beim Testen **OHNE** funktionierendes Order-Backend werden API-Aufrufe an den Order-Service per Mock vorgegeben, somit kann man unabhängig vom Order-Backend in Directus testen. Es gibt zusätzlich auch eine Strategie, Routing und Directus als Einheit mit lokal Docker-Containern zu testen, dies ist nicht Bestandteil des Routing-Projekts.

**Routing**

Der Quellcode für den Routing-Kernalgorithmus liegt im Ordner `routing`. Der Code und die Tests sind mit einer lokalen Python-Installation ausführbar. Zugriff auf den `OSRM`-Testserver ist nötig zum Ausführen von Tests mit `OSRM`-Aufrufen.

**Routing Datenbank-Service und API**

Die API, Datenbankstruktur und Migrations werden mit `Django` in Quellcode modelliert. Den Code findet man im Ordner `Routing_Api`. Die Tests-Ausführung muss hier mit Docker-Containern erfolgen, um die notwendigen Services für Datenbank und Messenger aufzubauen. Der Umgang mit Docker im routing wird im Folgenden ausführlicher erklärt.

**Quellcode-Dokumentation: Testbasierte Entwicklung und Quellcode-Kommentare**

Es wird testbasiert entwickelt, d.h. alle geforderten Funktionen sind mit Tests hinterlegt. Die Tests dienen neben der Qualitätssicherung demzufolge auch als Entwicklerdokumentation für den Quellcode. Zusätzlich wurde der Code mit aussagekräftigen Kommentaten hinterlegt.

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
 docker-compose up -d --build tester # nur den tester-Container für die Integrationstests -> deutlich schneller!
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

**Tester-Container**
```
docker-compose up -d --build tester
```
Hier kann man die Tests ausführen. Nähereres dazu in den Abschnitten zum Testen.

**RabbitMQ**

Dieser Container wird von Tester und Web automatisch gestartet. Liefert den Broker für die Event-Kommunikation.

**Celery-Beat und Celery-Worker**
```
docker-compose up -d --build celery-beat
docker-compose up -d --build celery-worker
```
Hiermit werden die nebenläufigen Tasks gestartet, siehe tasks.py.

### Integrationstests
* der Docker-Container "tester" führt nach dem Start die Tests aus, die Logs kann man sich in VisualStudioCode mit dem Docker-Plugin anschauen oder auch in Docker selbst
* die CI-Pipeline von GitHub Actions führt die Integrationstests aus

### Lokales Entwicklen, Debuggen und Unit-Tests

> **Hinweis**
>
> Alte Python-Packages können in Zukunft Probleme bereiten. Die Unittests funktionieren lokal auch mit Python 3.11 (Stand 02/2023). Für die Unittests ist eine deutlich abgespeckte Variante von requirements.txt ausreichend.

* Powershell oder Windows-Console und Visual Studio Code als Tools nutzen, die Tools müssen ihr WorkDir im Hauptordner des Routing-Repos haben
* generell: Funktionen getestet mit Python 3.9-64, Packages installieren per
```
py -3.9-64 -m pip install -r requirements.txt
```
* Achtung: in Firmen-Netzwerk-Zugang über DirectAccess muss man darauf achten, dass die Umgebungsvariablen für den Proxy NICHT gesetzt sind, sonst funktioniert pip install nicht

* optional: Umgebungsvariablen in Console laden aus Datei: env.bat - scheint im Normalfall nicht nötig zu sein
* Integrationstests können theoretisch gestartet werden mit 
```
py -3.9-64 ./Routing_Api/manage.py test -v 2
```
* aber für Integrationstests fehlt die Infrastruktur der DB-Services ... etc. -> tester-Container in Docker nutzen
* Unittests mit lokalem Python OHNE Docker
```
cd routing
py -3.9-64 -m unittest routing/tests.py -v # alle Tests einer einzelnen Testdatei
py -3.9-64 -m unittest -v # alle Test-Dateien in routing
py -3.9-64 -W ignore::DeprecationWarning -m unittest -v # wenn Warnungen nerven (Beheben der Warnung ist die bessere Lösung!)
py -3.9-64 -W error::DeprecationWarning -m unittest -v # wenn Warnungen als Fehler behandelt werden sollen (damit kann man die Stellen besser finden!)
py -3.9-64 -m unittest routing.tests.TestMeisenheim.test_Meisenheim -v # alternativ: einzelner Test
py -3.9-64 .\routing\testrunner.py profile # alternativ ueber testrunner, der auch profilen kann
```
* Debuggen und Ausführen der Test mit Debug-Funktion von VS-Code möglich, dazu das passende Python-Environment (hier: Python 3.9-64) auswählen und folgende Config fürs Launchen von Debugging nutzen:

```
{
    "name": "Python: RoutingUnitTests",
    "type": "python",
    "request": "launch",
    "cwd": "${workspaceFolder}/routing",
    "program": "",
    "args": ["-m", "unittest", "routing.tests.TestMeisenheim.test_Meisenheim"],
    "pythonArgs": [],
    "console": "integratedTerminal"
}
```

### Code Coverage beim Testen ermitteln
Package coverage muss installiert sein.

Coverage der Unittest:
```
pip install coverage
py -3.9-64 -m coverage erase # Daten bereinigen
py -3.9-64 -m coverage run -m unittest -v
py -3.9-64 -m coverage report # Kurzreport
py -3.9-64 -m coverage report -m # zeigt ungetestete Zeilen an
```
Coverage der Integrationstests im Tester-Container:
Analog zum Debuggen des Tester-Containers den Entrypoint in docker-compose deaktivieren und dann VS-Code an Tester-Container attachen. In VS-Code Console können
dann die Django-Tests folgendermassen ausgeführt werden mit Coverage:
```
cd www
python -m coverage run --source='.' manage.py test -v 2 --keepdb --noinput
python -m coverage report -m
```

Beachten: Code-Coverage der Http-Requests kann mit obiger einfacher Methode nicht gemessen werden, da die Requests in eigenen Threads laufen. Ansätze gibt es hier: https://coverage.readthedocs.io/en/6.3.2/subprocess.html#subprocess, hat aber erstmal nicht funktioniert. Abhilfe wäre: die fehlenden Zeilen auch durch direkte Tests zu prüfen, die nicht über Requests gehen.

### Profilen der Unittests
* Folgenden Befehl in Powershell eingeben (Arbeitsverzeichnis der Powershell: bUSnow-routing\routing)
* Ergebnisse werden in Textdateien abgelegt: bUSnow-routing\routing\test_profile_stats_...txt

```
py -3.9-64 .\routing\testrunner.py profile
```

* Erstellen eines Call-Tree aus dem pstats-dump (Datei test_profile_stats_dump.txt)

```
pip install gprof2dot
python -m gprof2dot -f pstats test_profile_stats_dump.txt -o test_profile_graph.dot
```
* Graphviz installieren und zu Path hinzufügen (Systemumgebungsvariablen - neu: C:\Program Files (x86)\Graphviz2.38\bin) und die dot-Datei in png-Bild konvertieren mit Powershell-Befehl
```
dot test_profile_graph.dot -Tpng -o test_profile_graph.png
```

### Debuggen der Integrationstests im Docker-Container "tester"

Ein paar wenige Anpassungen im Quellcode müssen vorgenommen werden.
Als erstes in docker-compose.yml den entrypoint des "tester"-Containers auskommentieren (das unterbindet den automatischen Start der Tests):

```
tester:
    build: .
    environment:
      - POSTGRES_HOST=db
      - RABBITMQ_HOST=rabbitmq
    env_file:
      - ./.env
    # command: python3 manage.py runserver 0.0.0.0:8000
    #entrypoint: python manage.py test -v 2 --keepdb --noinput # deactivate entrypoint for local debugging of container
    volumes:
      - ./maps:/maps
    ports:
      - "8000:8000"
    depends_on:
      - db
      - rabbitmq
```

Hinweise zu Problemen beim Debuggen mit VS Code in Docker-Containern:
- wsl2 sollte aktiviert werden, damit ist das Debuggen wesentlich stabiler gelaufen
- im März 2022 hat ein VS Code Update das Debuggen von Python on Docker Container kapput gemacht - prüfen ob ein Downgrade von VS Code ggfs. neu auftretende Probleme beheben kann

Als letztes sollte in docker-compose.yml bei "tester" die Umgebungsvariable BUSNOW_ENVIRONMENT=DEBUGGING gesetzt sein, damit man die Debug-Option in den Settings drin hat. Beim Aufrufen der Tests muss allerdings trotzdem der Schalter "--debug-mode" gesetzt sein.

Danach docker compose neu ausführen. 

Dann im Docker-Explorer von VS-Code den laufenden tester-Container mit Rechtsklick auswählen und dort "Attach VS Code" ausführen. Es öffent sich ein neues VS-Code-Fenster, das eventuell noch ein paar Apps im Container installiert. Um die Files browsen zu können, muss man
im Datei-Explorer des VS-Code bei "Open-Folder" KEINEN Unterordner sondern Top-Level eingeben ("/"). 
Es müssen alle Ordner und Dateien zu sehen sein, dort liegt manage.py im Ordner "www".
Aufpassen muss man, dass in VS-Code die passende Python-Umgebung ausgewählt wurde, damit alle Packages vorhanden sind!

Bei Problemen mit dem Anhängen an den Docker-Container kann man probieren, in Docker-Settings 1. wsl2 zu deaktivieren und 2. zu schauen, dass in File-Sharing was sinnvolles drinsteht, dazu Hinweise siehe https://code.visualstudio.com/docs/remote/containers.

Debuggen funktioniert nun wie immer mit der passenden launch.json. Das Testing von Django erlaubt auch einzelne Tests auszuwählen. Ein Beispiel:

```
        {
            "name": "Python: IntegrationTests",
            "type": "python",
            "request": "launch",
            "cwd": "${workspaceFolder}/www",
            "program": "manage.py",
            "args": ["test", "Routing_Api.Mobis.tests.UnverbindlicheAnfrage.test_too_many_mobies_one_request_above_bus_capacity_200_false", "-v", "2", "--keepdb", "--noinput", "--debug-mode"],
            "pythonArgs": [],
            "console": "integratedTerminal"
        }
```

Noch ein Hinweis: Änderungen in 'routing' kommen nicht einfach an im Python-Programm, dazu muss man im VS-Code-Terminal routing neu compilieren und installieren, also:

```
cd .. # wenn man in www ist
cd routing 
python -m compileall .
pip install --no-cache-dir .
```

### Debuggen des routing-service in aws pod
Voraussetzung: kubectl, k9s, aws-credentials sind vorhanden.
Kubernetes-Plugin in VS-Code installieren.

Dann im Kubernetes-Plugin anschauen, was in der aws gefunden wird. Man kann sich anhand der Bezeichnungen in k9s zum richtigen Service durchhangeln, den man debuggen möchte. Rechtsklick, z.B. auf development-routing-.... und "attach VS Code". Das Anhängen kann sehr lang dauern (5-10 Minuten). Dann muss man bei OpenFolder den Toplevel-Folder "/" angeben und sieht den python-Code und alles mögliche.

Einfache Möglichkeit des debuggens:
- Pythoncode anpassen wie gewünscht 
- prints in Python einbauen funktioniert, damit Ausgaben entstehen, die man in k9s anschauen kann, z.B. print('test')
- in k9s in der Übersicht aller services kann man mit "s" den scale-Befehl aufrufen und z.B. "development-routing" auf einen Prozess skalieren und beim Debuggen an genau dem vorbei zu kommen
- dann im Browser die http-Abfrage eingeben die man untersuchen möchte und schauen, was in den Logs passiert
- damit der pod aktualisiert wird auf den angepassten Code muss man den gunicorn worker zu einem restart zwingen, das geht mit folgendem Hack:
```
in k9s aus den logs raussuchen, mit welcher PID der worker von gunicorn läuft
dann in k9s in shell gehen oder das VS-Code Terminal nutzen und ausführen: kill -HUP <pid> (zB "kill -HUP 1043")
dann sieht man in logs, dass worker neu startet und dann kommt aktualisierter Code auch an
```
- bei Änderungen in "routing" muss man in der Konsole zusätzlich neu kompilieren und installieren, siehe Hinweis zum debuggen in Docker-Container.

Ändern von Umgebungsvariablen im deployten service "routing"
- aufnehmen in Deploy, indem Werte in yaml-File in DevOps ergänzt werden
- manuelles und temporäres eintragen in aws-pods OHNE neuen Deploy: Datei mit Powershell-Befehl "kubectl edit cm/development-environment -n mp-dev" öffnen und editieren, wenn man dann services neu startet, haben die die env Variablen drin

Restart des Routing-Service
Auf diese Weise startet man service neu, ohne dass der Service ausfällt:
"kubectl rollout restart deployment/development-routing deployment/development-routing-celery-worker deployment/development-routing-celery-beat -n mp-dev"

## Django-Migrations erstellen, wenn Models angepasst wurden
Models anpassen und dann folgendermaßen neue Migrations erstellen:
Analog zum Debuggen des Tester-Containers den Entrypoint in docker-compose deaktivieren und dann VS-Code an Tester-Container attachen. In VS-Code Console können
dann die Django-Migrations folgendermassen generiert werden:
```
cd www
python ./manage.py makemigrations --name='wheelchairs_added' # Name passend wählen!
```

## ORTools 
### Das TSP-Problem wird vom Solver als INTEGER-Optimierung angesehen
Wichtig zu wissen: https://developers.google.com/optimization/cp/cp_solver
Das heißt: alle Inputs für den Optimierer sind als Integer anzusehen. In der aktuellen Implementierung sind:
- Zeiten in Minuten: kleinste Einheit ist eine Minute
- Entfernungen: nicht im Optimierer berücksichtigt (wird alles über Zeiten gemacht)

## OSRM Routing
### OSRM aktivieren per Env-Variable
Im Deploy-Projekt muss man die Env-Variable eintragen env-config-map.yaml, damit sie standardmäßig ausgerollt wird.

Manuell kann man es temporär machen, indem man mit dem Befehl "kubectl edit cm/development-environment -n mp-dev" die Config-Datei anpasst und die Routing-Services neu startet.
Das wären die ursprünglich angelegten OSRM-Services in der Erzmobil-Umgebung **[Hinweis: diese wurden 09/2022 gelöscht; gegebenenfalls diksutieren, ob wieder eine OSRM-Instanz für Erzmobil erstellt wird oder ob (nur fürs Testing!) auf die OSRM-Test-Url http://router.project-osrm.org verwiesen wird]**:
```
OSRM_API_URI: alte_url # (für prod) oder für dev: OSRM_API_URI=alte_url 
```
Wichtig: Datei nach dem Editieren schließen und dann die Pods für routing und celery_worker neu starten (zB durch scalen auf 0 und dann wieder auf 2 scalen).


