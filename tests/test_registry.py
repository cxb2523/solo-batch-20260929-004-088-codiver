"""Registry decisions: decorator auto-discovery, fixed order, stability."""

import detectors.base as base
from detectors.base import (registered_detectors, registry_snapshot,
                            register_detector, REGISTRY, _REGISTRY_BY_NAME)


def test_all_four_detectors_auto_registered():
    names = {item["name"] for item in registry_snapshot()}
    assert {"design", "implementation", "naming", "documentation"} <= names


def test_registry_order_is_explicit_not_import_order():
    snapshot = registry_snapshot()
    orders = [item["order"] for item in snapshot]
    assert orders == sorted(orders)
    assert [item["name"] for item in snapshot[:4]] == [
        "design", "implementation", "naming", "documentation"]


def test_registration_is_idempotent_under_reimport():
    before = len(registry_snapshot())
    import detectors.design  # noqa: F401  (re-import must not duplicate)
    import detectors.naming_docs  # noqa: F401
    after = len(registry_snapshot())
    assert before == after


def test_config_toggles_detectors():
    all_detectors = registered_detectors({})
    only_design = registered_detectors({"design": True,
                                        "implementation": False,
                                        "naming": False,
                                        "documentation": False})
    assert len(all_detectors) >= 4
    assert [d.detector_name for d in only_design] == ["design"]


def test_shuffling_registry_entries_does_not_change_dispatch_order():
    original = list(base.REGISTRY)
    try:
        base.REGISTRY.sort(key=lambda item: -item["order"])
        names = [item["name"] for item in registry_snapshot()]
        # registry_snapshot re-sorts by (order, name)
        assert names[:4] == ["design", "implementation", "naming",
                             "documentation"]
    finally:
        base.REGISTRY[:] = original
        base.REGISTRY.sort(key=lambda item: (item["order"], item["name"]))


def test_decorator_registers_metadata():
    @register_detector(name="temp-detector", category="Test", order=999,
                       config_key="temp")
    class Temp:
        pass

    try:
        entry = _REGISTRY_BY_NAME["temp-detector"]
        assert entry["category"] == "Test"
        assert entry["config_key"] == "temp"
    finally:
        REGISTRY.remove(_REGISTRY_BY_NAME.pop("temp-detector"))
