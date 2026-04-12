# Setup

## Requisiti

- Python 3.11+
- Token Telegram bot
- API key Groq

## Boot locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python main.py
```

## Deploy persistente su VPS Ubuntu

Per tenere il bot sempre attivo e farlo ripartire automaticamente dopo un reboot
della VPS, usa `systemd` con il file
[`deploy/cumbot.service`](/home/ubuntu/Desktop/CumBot/deploy/cumbot.service).

Installazione:

```bash
sudo cp /home/ubuntu/Desktop/CumBot/deploy/cumbot.service /etc/systemd/system/cumbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now cumbot
```

Gestione:

```bash
sudo systemctl status cumbot
sudo systemctl restart cumbot
sudo systemctl stop cumbot
sudo systemctl start cumbot
journalctl -u cumbot -f
```

Se modifichi il file `.service`, ricorda:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cumbot
```

## File attesi

- `data/export.json` oppure un singolo `data/**/result.json` per il training offline
- `runtime/cumbot.sqlite3` creato automaticamente
- `models/` popolata da `/retrain` o training manuale

## Training manuale

```bash
python -c "from cumbot.markov.trainer import train_all; print(train_all())"
```

## Ispezione locale Markov

```bash
.venv/bin/python -m cumbot.markov.report summary
.venv/bin/python -m cumbot.markov.report sample --count 8
.venv/bin/python -m cumbot.markov.report sample --persona 379826097 --count 8
.venv/bin/python -m cumbot.markov.report analyze --limit 50000
```
