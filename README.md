# CumBot

CumBot e un bot Telegram per chat di gruppo che combina:

- generazione Markov chat-scoped;
- contesto live recente per gruppo;
- refiner e classifier Groq opzionali;
- monitoraggio output, reaction, GIF/sticker corpus;
- retrain progressivo per chat con scheduler automatico.

## Scopo del progetto

L'obiettivo e far parlare il bot come una specifica chat Telegram, mantenendo:

- stile lessicale del gruppo;
- personalita per utente/persona;
- adattamento continuo ai messaggi recenti;
- separazione netta tra gruppi diversi.

Il progetto e pensato per uso self-hosted su VPS Ubuntu.

## Cosa contiene la repo

- codice applicativo Python del bot;
- documentazione operativa in `docs/`;
- unit file `systemd` in `deploy/`;
- test automatici;
- configurazione di esempio via `.env.example`.

## Cosa NON viene pubblicato

La repository deve escludere:

- export Telegram e dataset raw in `data/`;
- modelli addestrati in `models/`;
- database runtime e stato locale in `runtime/`;
- file `.env` e qualunque segreto/API key;
- cache locali, virtualenv e log.

Queste esclusioni sono gestite in `.gitignore`.

## Stack tecnico

- Python 3.11+
- `python-telegram-bot`
- `markovify`
- SQLite
- Groq API
- `systemd` per il deploy persistente su VPS

## Avvio locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python main.py
```

## Deploy su VPS

Il bot puo essere eseguito come servizio persistente con:

```bash
sudo cp deploy/cumbot.service /etc/systemd/system/cumbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now cumbot
```

Comandi utili:

```bash
sudo systemctl status cumbot
sudo systemctl restart cumbot
journalctl -u cumbot -f
```

## Note privacy

Questo progetto lavora su chat export e corpus testuali potenzialmente sensibili.
Prima di pubblicare codice o condividerlo:

- verifica sempre `git status`;
- assicurati che `.env`, `data/`, `models/` e `runtime/` non siano tracciati;
- evita di committare ID, token, export o database reali;
- preferisci repo private finche non hai fatto una review completa dei file.

## Stato attuale

Lo stato operativo aggiornato del progetto e documentato soprattutto in:

- [`docs/runbook.md`](/home/ubuntu/Desktop/CumBot/docs/runbook.md)
- [`docs/worklog.md`](/home/ubuntu/Desktop/CumBot/docs/worklog.md)
- [`docs/chat_scoped_training_plan.md`](/home/ubuntu/Desktop/CumBot/docs/chat_scoped_training_plan.md)
