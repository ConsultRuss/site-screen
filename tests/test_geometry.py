"""Hand-checked geometry: distance and compactness."""

import math

from pipeline.geometry import haversine_miles, polsby_popper


def test_haversine_zero_distance():
    assert haversine_miles(29.0, -98.0, 29.0, -98.0) == 0.0


def test_haversine_one_degree_latitude_is_about_69_miles():
    # One degree of latitude is ~69 statute miles anywhere on Earth.
    d = haversine_miles(29.0, -98.0, 30.0, -98.0)
    assert abs(d - 69.0) < 0.5


def test_polsby_popper_circle_is_one():
    # Circle radius 1: area = pi, perimeter = 2*pi -> compactness = 1.
    assert abs(polsby_popper(math.pi, 2 * math.pi) - 1.0) < 1e-9


def test_polsby_popper_square_is_known_value():
    # Unit square: area 1, perimeter 4 -> 4*pi/16 = pi/4 ~= 0.785.
    assert abs(polsby_popper(1.0, 4.0) - math.pi / 4) < 1e-9
