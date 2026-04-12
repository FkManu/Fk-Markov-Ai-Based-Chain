# Testing

## Copertura minima attuale

- Parser del campo `messages[].text`
- Normalizzazione user ID da export Telegram
- Filtri base del trainer
- Buffer contesto recente
- Fallback del generatore Markov
- Troncamento delle bozze Markov troppo lunghe
- Monitoring persistente degli output generati
- Candidate generation e ranking Markov
- Normalizzazione selettiva del corpus
- Analisi locale del corpus e dei motivi di scarto
- Risoluzione di `@user` in mention reali
- Cooldown autopost basato sul numero di messaggi
- Aggregazione reaction sugli output monitorati

## Comandi

```bash
.venv/bin/python -m pytest
python3 -m compileall .
```

## Gap noti

- Mancano test end-to-end con Telegram update reali
- Mancano test integrazione DB async
- Mancano test end-to-end per update Telegram reaction reali
- Mancano test integrazione completi per flow admin
