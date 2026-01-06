import pytest
from data.creature import Creature, create, get_one, modify, delete, curs, conn
from errors import Missing, Duplicate

@pytest.fixture(autouse=True)
def clear_table():
    """Очистка таблицы перед каждым тестом."""
    curs.execute("DELETE FROM creature")
    conn.commit()


@pytest.fixture
def sample():
    return Creature(
        name="Yeti",
        country="CN",
        area="Himalayas",
        description="Harmless Himalayan",
        aka="Abominable Snowman",
    )


def test_create(sample):
    resp = create(sample)
    assert resp.name == sample.name
    assert resp.description == sample.description


def test_create_duplicate(sample):
    create(sample)
    with pytest.raises(Duplicate):
        create(sample)


def test_get_one(sample):
    create(sample)
    resp = get_one(sample.name)
    assert resp.name == sample.name


def test_get_one_missing():
    with pytest.raises(Missing):
        get_one("boxturtle")


def test_modify(sample):
    create(sample)
    sample.description = "New desc"
    resp = modify(sample)
    assert resp.description == "New desc"


def test_modify_missing():
    thing = Creature(
        name="snurfle",
        country="RU",
        area="",
        description="some thing",
        aka="",
    )
    with pytest.raises(Missing):
        modify(thing)


def test_delete(sample):
    create(sample)
    assert delete(sample.name)
    with pytest.raises(Missing):
        get_one(sample.name)


def test_delete_missing(sample):
    with pytest.raises(Missing):
        delete("ghost")
