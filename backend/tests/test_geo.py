import pytest

from app.services.geo import haversine_miles


def test_distance_from_a_point_to_itself_is_zero():
    assert haversine_miles(41.85, -87.65, 41.85, -87.65) == 0


def test_distance_between_two_known_cities():
    # Chicago to Milwaukee — roughly 80 miles, a useful sanity check that
    # the formula and units (miles, not km) are both right.
    chicago = (41.8781, -87.6298)
    milwaukee = (43.0389, -87.9065)
    distance = haversine_miles(*chicago, *milwaukee)
    assert distance == pytest.approx(80, abs=5)


def test_distance_is_symmetric():
    a = (41.85, -87.65)
    b = (41.90, -87.60)
    assert haversine_miles(*a, *b) == pytest.approx(haversine_miles(*b, *a))
