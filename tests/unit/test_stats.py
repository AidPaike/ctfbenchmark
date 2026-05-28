from droplet.manager import _ratio


def test_ratio_handles_zero_denominator() -> None:
    assert _ratio(1, 0) == 0.0


def test_ratio_rounds() -> None:
    assert _ratio(1, 3) == 0.3333
