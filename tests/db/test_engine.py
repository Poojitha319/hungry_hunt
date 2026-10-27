from hungry_hunt.db import make_engine


def test_make_engine_sqlite_has_no_recycle():
    engine = make_engine("sqlite://")
    assert engine.pool._recycle == -1


def test_make_engine_postgres_sets_pre_ping_and_recycle():
    engine = make_engine("postgresql://u:p@localhost/db")
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 300
    assert engine.url.drivername == "postgresql+psycopg"
