from cumbot.db.state import Announcement
from cumbot.handlers import annuncio_handler


def test_annuncio_view_text_shows_italian_timezone(monkeypatch) -> None:
    monkeypatch.setattr(annuncio_handler.config, "ANNOUNCEMENT_TIMEZONE", "Europe/Rome")
    ann = Announcement(
        id=1,
        chat_id=-1001,
        text="Messaggio di prova",
        hour=21,
        minute=0,
        enabled=True,
        created_at="2026-04-11T00:00:00+00:00",
    )
    text = annuncio_handler._ann_view_text(ann)
    assert "Europe/Rome" in text
    assert "ora italiana" in text
