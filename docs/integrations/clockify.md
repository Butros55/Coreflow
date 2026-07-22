# Clockify-Integration — API-Vertrag und Sync-Regeln

Referenz für `apps/integrations/clockify/`. Beschreibt den verwendeten Teil der
Clockify-API (https://docs.clockify.me) und die Richtungs-/Dedup-Regeln, die
Coreflow durchsetzt.

## 1. Grundsätze

* **Optional, für immer.** Die interne Zeiterfassung ist die primäre
  Implementierung. `CLOCKIFY_ENABLED=false` ist eine dauerhaft unterstützte
  Konfiguration; jede Task beginnt mit einem Enabled-Check und kostet
  deaktiviert genau einen Early-Return pro Beat-Tick.
* **Beidseitiger Spiegel.** Kunden, Projekte, Tags und Zeiteinträge werden in
  beide Richtungen synchronisiert; beide Systeme sollen denselben Stand zeigen.
* **Keine Dopplungen.** Ein Zeiteintrag, der in Lexware **und** Clockify
  existiert, ist lokal EIN Eintrag mit zwei Herkunfts-Tags (§5.4) — nie zwei
  Zeilen.

## 2. Authentifizierung & Basis

| | |
|---|---|
| Basis-URL | `https://api.clockify.me/api/v1` (`CLOCKIFY_API_BASE_URL`) |
| Auth | Header `X-Api-Key: <key>` — Personal API Key aus *Profile settings → Manage API keys*; es gelten die Rechte dieses Users |
| Workspace | Alle Ressourcen außer `/user` und `/workspaces` sind Workspace-scoped: `/workspaces/{workspaceId}/…`. `CLOCKIFY_WORKSPACE_ID` pinnt den Workspace; leer ⇒ `activeWorkspace` des Users (Fallback `defaultWorkspace`, dann erster Workspace) |
| Rate limit | ~50 req/s pro Key. Coreflow drosselt selbst auf 5 req/s (globaler Token-Bucket); `Retry-After` wird bei 429 respektiert |
| Fehlerformat | `{"message": "…", "code": <int>}` — gematcht wird ausschließlich auf den HTTP-Status, nie auf Text oder internen Code |

## 3. Verwendete Endpunkte

Listen liefern **nackte JSON-Arrays** (kein Envelope, kein Total). Pagination
über `page`/`page-size`; die letzte Seite ist die erste unvollständige.

| Ressource | Endpunkte |
|---|---|
| Konto | `GET /user`, `GET /workspaces` (Verbindungstest, Workspace-Auflösung) |
| Kunden | `GET/POST /workspaces/{id}/clients`, `GET /clients/{cid}` |
| Projekte | `GET/POST /workspaces/{id}/projects`, `GET /projects/{pid}` |
| Tags | `GET/POST /workspaces/{id}/tags` |
| Tasks | `GET/POST /workspaces/{id}/projects/{pid}/tasks`, `GET …/tasks/{tid}` |
| Mitglieder | `GET /workspaces/{id}/users` |
| Zeiteinträge | `GET /workspaces/{id}/user/{uid}/time-entries?start=&end=` (pro User!), `GET/PUT/DELETE /workspaces/{id}/time-entries/{eid}`, `POST /workspaces/{id}/time-entries` (eigener User) bzw. `POST /workspaces/{id}/user/{uid}/time-entries` (fremder User, braucht "Add time for others") |

Eigenheiten, auf die sich der Code verlässt:

* Zeiten sind ISO-8601-UTC (`2026-07-10T09:00:00Z`), teils mit Millisekunden.
  Ein **laufender** Eintrag hat `timeInterval.end == null` — es gibt kein
  separates Flag. Die Dauer wird immer aus `start`/`end` berechnet, der
  ISO-8601-Duration-String wird nie geparst.
* `PUT /time-entries/{id}` **ersetzt**: jedes beschreibbare Feld (`start`,
  `end`, `billable`, `description`, `projectId`, `taskId`, `tagIds`) muss im
  Payload stehen, sonst wird es remote geleert.
* Stundensätze werden **nicht** gespiegelt (Einheit/Verfügbarkeit ist
  Plan-abhängig); importierte Einträge werden über die lokale
  Satz-Auflösungskette bepreist.

## 4. Semantisches Mapping

| Clockify | Coreflow | Anmerkung |
|---|---|---|
| Client | `crm.Client` | Name-Match (case-insensitive), sonst Neuanlage |
| Project | `projects.Project` | Projekt ohne Client hängt am Platzhalter-Kunden „Clockify (ohne Kunde)“ — lokale Projekte brauchen zwingend einen Kunden |
| Tag | `timetracking.ServiceType` | Workspace-global wie Leistungsarten. Der Coreflow-Marker-Tag **„Abgerechnet“** (§5.6) ist ausgenommen |
| Task | `projects.Task` | Nur Verknüpfung per Titel-Match im Projekt. Lokale Tasks werden **nie** aus Clockify erzeugt (bräuchten ein Board); Remote-Tasks werden beim Entry-Push bei Bedarf angelegt |
| Time entry | `timetracking.TimeEntry` | `source=clockify` bei Import; der Kunde kommt über das Projekt, ohne Projekt ⇒ Platzhalter-Kunde |
| User | `accounts.User` | Nur E-Mail-Match. Sync legt nirgends User an |

## 5. Sync-Regeln

### 5.1 Stammdaten (Kunden/Projekte/Tags)

Strukturell bidirektional: jedes Remote-Objekt bekommt ein lokales Gegenstück
(Name-Match oder Neuanlage), jedes lokale ein Remote-Gegenstück (Anlage wenn
unverknüpft — im 15-Minuten-Takt und beim Full Sync). Nach der Verknüpfung
werden CRM-Felder **nicht** laufend überschrieben; das Mapping lebt in
`ExternalObjectLink`. Mehrdeutige Name-Matches werden zum `SyncConflict`
(`ambiguous_match`), nie geraten.

### 5.2 Zeiteinträge eingehend

Pro verknüpftem User in 31-Tage-Fenstern (inkrementell 14 Tage zurück, Full
Sync 365). Laufende Einträge werden übersprungen, bis sie stoppen. Jeder Write
ist über den `sync_hash` der normalisierten Projektion idempotent — wiederholte
Webhooks und überlappende Fenster sind No-ops. Remote-Änderungen an lokal
abgerechneten Einträgen (`invoice_draft_created`/`billed`/`cancelled`) und
beidseitige Änderungen werden zum `SyncConflict`, nie automatisch gemergt.
Remote-Löschungen löschen den lokalen Spiegel — außer er ist abgerechnet
(Konflikt) oder stammt aus Lexware (nur das Clockify-Tag fällt weg).

### 5.3 Zeiteinträge ausgehend

* **Sofort:** Anlage/Änderung/Löschung über die Coreflow-API (inkl.
  Timer-Stopp) wird `on_commit` per Celery gespiegelt. Sync-eigene Writes
  laufen nicht durch die Views — kein Echo-Loop.
* **Periodisch:** unverknüpfte lokale Einträge (`manual`/`timer`, jünger als
  `CLOCKIFY_PUSH_LOOKBACK_DAYS`) werden angelegt; das Fenster verhindert, dass
  eine frische Verbindung Jahre an Historie in Clockify kippt.
  Lexware-Rekonstruktionen werden **nie** gepusht (synthetische Uhrzeiten).
* Lokale Edits an verknüpften Einträgen werden zurückgepusht, solange die
  Remote-Seite unverändert ist; der PUT-Payload erhält nicht auflösbare
  Remote-IDs und fremde Tags (z. B. „Abgerechnet“).

### 5.4 Lexware-Dedup („ein Eintrag, zwei Tags“)

Bevor ein Remote-Eintrag als neuer `TimeEntry` angelegt wird, sucht der Sync
einen unverknüpften lokalen Zwilling:

1. **Exakt** (beliebige Quelle): gleicher Kunde, Start ±60 s, gleiche Stunden
   (auf 2 Nachkommastellen — die Präzision der Rechnungszeile).
2. **Lexware-Rekonstruktion** (`source=lexware`): gleiche Stunden, gleicher
   Kunde, und der Remote-Start fällt in den Leistungszeitraum der verknüpften
   Rechnung (Rekonstruktionen haben synthetische Uhrzeiten, daher zählt der
   Rechnungszeitraum, nicht die Uhrzeit).

Ein Treffer wird **verknüpft statt dupliziert**: der Eintrag behält Status,
Beträge und Rechnungszuordnung (Lexware-Tag) und bekommt zusätzlich den
Clockify-Link (Clockify-Tag). Ein verbrauchter Kandidat trägt den Link und kann
nie doppelt matchen. Einträge, die nur aus Clockify kommen, tragen nur das
Clockify-Tag. Grenze des Verfahrens: Clockify-Einträge **ohne Projekt** haben
keinen Kunden und können daher weder Rechnungen noch Lexware-Zwillingen
zugeordnet werden — in Clockify Projekte pflegen.

### 5.5 Der UI-Tag

`TimeEntry.integration_tags` (Serializer-Feld): `lexware`, wenn der Eintrag aus
dem Lexware-Import stammt oder von ihm einer Rechnung zugeordnet wurde;
`clockify`, wenn ein aktiver `ExternalObjectLink` existiert. Beides gleichzeitig
ist der Normalfall nach §5.4.

### 5.6 Abrechnungsstatus

Clockify kennt nur `billable` ja/nein, keinen „abgerechnet“-Zustand. Wird eine
Coreflow-Rechnung finalisiert, bekommen verknüpfte Einträge in Clockify den
Workspace-Tag **„Abgerechnet“** (angelegt bei Bedarf; per GET+PUT, damit kein
anderes Feld angefasst wird; retried mit Backoff). Der Tag ist vom
Leistungsarten-Mapping ausgenommen und sein Echo im nächsten Sync wird als
Konvergenz erkannt, nicht als Konflikt.

## 6. Webhooks (Sofort-Erkennung)

* Anlage **manuell** im Clockify-UI (Workspace-Einstellungen → *Webhooks*).
  Ein Webhook abonniert genau **einen** Event-Typ ⇒ pro Event einen Webhook auf
  `<API_URL>/webhooks/clockify/` anlegen. Relevante Events: `NEW_TIME_ENTRY`,
  `TIME_ENTRY_UPDATED`, `TIME_ENTRY_DELETED`, `TIMER_STOPPED`, `NEW_PROJECT`,
  `PROJECT_UPDATED`, `PROJECT_DELETED`, `NEW_CLIENT`, `CLIENT_UPDATED`,
  `CLIENT_DELETED`, `NEW_TAG`, `TAG_UPDATED`, `TAG_DELETED`.
* Jede Zustellung trägt `clockify-webhook-event-type` (Event-Name) und
  `clockify-signature` (das beim Anlegen angezeigte Signing-Token des
  Webhooks). Verifikation: Konstantzeit-Vergleich gegen
  `CLOCKIFY_WEBHOOK_TOKEN` — **kommasepariert**, ein Token je Webhook.
* Payload ist die volle Entität; verarbeitet wird trotzdem
  **fetch-then-reconcile** (der Body kann bei Verarbeitung veraltet sein).
  Persist-then-ack: Event-Zeile zuerst, Verarbeitung in Celery.
* Dedupe-Key = SHA-256 über `(event, id, Body-Digest)` — identische Replays
  fallen weg, echte Änderungen (gleiche ID, anderer Inhalt) nicht.
* Zustellgarantien sind undokumentiert ⇒ Duplikate (Dedupe), Lücken
  (periodischer Sync als Backstop, `webhooks:process-pending` alle 5 min) und
  Out-of-order (fetch-then-reconcile) sind alle abgedeckt.
* Ohne konfigurierte Tokens bleibt der Endpunkt dunkel (403 bzw. 404 bei
  deaktivierter Integration); der 15-Minuten-Sync läuft unabhängig davon.

## 7. Konfiguration

```
CLOCKIFY_ENABLED=true
CLOCKIFY_API_BASE_URL=https://api.clockify.me/api/v1
CLOCKIFY_API_KEY=<Profile settings → Manage API keys>
CLOCKIFY_WORKSPACE_ID=            # optional, sonst activeWorkspace
CLOCKIFY_WEBHOOK_TOKEN=<token1>,<token2>,…
CLOCKIFY_SYNC_INTERVAL_MINUTES=15
CLOCKIFY_PUSH_LOOKBACK_DAYS=30
```

Verbindungstest im Integrations-Center (`POST /integrations/clockify/test`)
cached `GET /user` + Workspace als `ProviderProfile` — `raw_profile.user.id`
ist load-bearing: der Entry-Push entscheidet damit zwischen „eigener User“
(`POST /time-entries`) und „Add time for others“ (`POST /user/{uid}/…`).

## 8. Tests

Kein Sandbox-Account: alles läuft gegen respx-Mocks
(`apps/integrations/tests/test_clockify_sync.py`); der `_no_network`-Guard der
Suite macht einen vergessenen Mock zum lauten Fehler statt zum Live-Call.
