from cv_engine.services.line_counter import LineCounter


def _make_tracked(track_id: int, y1: int, y2: int) -> dict:
    return {"track_id": track_id, "bbox": [0, y1, 100, y2], "confidence": 0.9}


def test_empty_input():
    counter = LineCounter(line_y=400)
    n = counter.update([])
    assert n == 0
    assert counter.total_count == 0


def test_first_frame_no_count():
    counter = LineCounter(line_y=400)
    obj = _make_tracked(1, 300, 350)
    n = counter.update([obj])
    assert n == 0
    assert counter.total_count == 0
    assert obj["counted"] is False


def test_crossing_above_to_below():
    counter = LineCounter(line_y=400)
    counter.update([_make_tracked(1, 300, 350)])

    obj = _make_tracked(1, 300, 550)
    n = counter.update([obj])
    assert n == 1
    assert counter.total_count == 1
    assert obj["counted"] is True


def test_no_count_backward_movement():
    counter = LineCounter(line_y=400)
    obj_below = _make_tracked(1, 300, 500)
    counter.update([obj_below])

    obj_above = _make_tracked(1, 100, 200)
    n = counter.update([obj_above])
    assert n == 0
    assert counter.total_count == 0
    assert obj_above["counted"] is False


def test_duplicate_prevention():
    counter = LineCounter(line_y=400)
    counter.update([_make_tracked(1, 300, 350)])

    obj = _make_tracked(1, 300, 550)
    counter.update([obj])
    assert counter.total_count == 1

    obj2 = _make_tracked(1, 300, 550)
    counter.update([obj2])
    assert counter.total_count == 1
    assert obj2["counted"] is True


def test_multiple_objects():
    counter = LineCounter(line_y=400)

    counter.update([_make_tracked(1, 300, 350), _make_tracked(2, 300, 350)])
    assert counter.total_count == 0

    objs = [
        _make_tracked(1, 300, 550),
        _make_tracked(2, 300, 550),
    ]
    n = counter.update(objs)
    assert n == 2
    assert counter.total_count == 2


def test_exact_on_line():
    counter = LineCounter(line_y=400, hysteresis=0)

    obj1 = _make_tracked(1, 300, 350)
    counter.update([obj1])

    obj2 = _make_tracked(1, 350, 450)
    n = counter.update([obj2])
    assert n == 1
    assert counter.total_count == 1


def test_hysteresis_prevents_noise():
    counter = LineCounter(line_y=400, hysteresis=10)

    obj_near = _make_tracked(1, 300, 402)
    counter.update([obj_near])

    obj_near2 = _make_tracked(1, 299, 405)
    n = counter.update([obj_near2])
    assert n == 0


def test_hysteresis_allows_clear_crossing():
    counter = LineCounter(line_y=400, hysteresis=10)

    obj1 = _make_tracked(1, 300, 350)
    counter.update([obj1])

    obj2 = _make_tracked(1, 300, 560)
    n = counter.update([obj2])
    assert n == 1
    assert counter.total_count == 1


def test_properties():
    counter = LineCounter(line_y=400)
    assert counter.line_y == 400

    counter.line_y = 500
    assert counter.line_y == 500

    assert isinstance(counter.crossed_ids, set)
