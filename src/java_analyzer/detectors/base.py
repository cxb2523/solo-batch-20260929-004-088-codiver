"""
Abstract Base Class for Code Smell Detectors
Defines the contract that all detector implementations must follow

Registry decision
-----------------
Detectors register themselves with ``@register_detector`` (decorator
auto-discovery) instead of being hand-listed in a central ``if/else``
factory.  Import order is deliberately *not* part of the contract: every
registration carries an explicit integer ``order`` and
``registered_detectors()`` always returns instances sorted by
``(order, name)``.  Registration is idempotent per detector name, so
re-importing a detector module (possible because ``app.py`` puts both
``src`` and ``src/java_analyzer`` on ``sys.path``) cannot double-count.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import javalang


# Ordered registry entries:
# {"name", "category", "order", "config_key", "class"}
REGISTRY: List[Dict[str, Any]] = []
_REGISTRY_BY_NAME: Dict[str, Dict[str, Any]] = {}


def register_detector(name: str, category: str, order: int,
                      config_key: Optional[str] = None):
    """
    Decorator that adds a detector class to the global registry.

    Args:
        name: Unique, stable detector identifier (used for provenance).
        category: Default issue category of the detector.
        order: Explicit dispatch order (smaller runs first). This is what
            makes findings ordering independent of module import order.
        config_key: Key in the engine config dict that toggles this
            detector; ``None`` means the detector is always enabled.
    """
    def decorator(cls):
        cls.detector_name = name
        cls.detector_category = category
        cls.detector_order = order
        cls.config_key = config_key
        if name not in _REGISTRY_BY_NAME:
            entry = {
                "name": name,
                "category": category,
                "order": order,
                "config_key": config_key,
                "class": cls,
            }
            REGISTRY.append(entry)
            _REGISTRY_BY_NAME[name] = entry
            REGISTRY.sort(key=lambda item: (item["order"], item["name"]))
        return cls
    return decorator


def registered_detectors(config: Optional[Dict[str, bool]] = None
                         ) -> List["CodeSmell"]:
    """
    Build detector instances in canonical registry order, filtered by
    the user configuration.

    Args:
        config: Mapping of ``config_key`` -> enabled flag. Missing keys
            default to enabled (True).

    Returns:
        Detector instances sorted by ``(order, name)``.
    """
    config = config or {}
    instances: List[CodeSmell] = []
    # Defensive sort: dispatch follows the explicit ``order`` even if the
    # underlying registry list was mutated or modules imported out of order.
    ordered = sorted(REGISTRY, key=lambda item: (item["order"], item["name"]))
    for entry in ordered:
        key = entry["config_key"]
        if key is None or config.get(key, True):
            instances.append(entry["class"]())
    return instances


def registry_snapshot() -> List[Dict[str, Any]]:
    """Return a lightweight copy of the ordered registry (for tracing/tests)."""
    ordered = sorted(REGISTRY, key=lambda item: (item["order"], item["name"]))
    return [
        {
            "name": item["name"],
            "category": item["category"],
            "order": item["order"],
            "config_key": item["config_key"],
        }
        for item in ordered
    ]


class CodeSmell(ABC):
    """
    Abstract base class for all code smell detectors.
    Implements the Strategy Pattern for different detection algorithms.
    """

    # Populated by @register_detector; sensible defaults for bare instances.
    detector_name = "unnamed-detector"
    detector_category = "Unknown"
    detector_order = 100
    config_key = None
    
    @abstractmethod
    def detect(self, tree: javalang.tree.CompilationUnit, lines: List[str],
               ctx=None) -> List[Dict[str, Any]]:
        """
        Detect code smells in the given AST tree.
        
        Args:
            tree: Parsed Java AST (Abstract Syntax Tree)
            lines: Source code split into lines
            ctx: Optional DetectionContext used to record helper-decision
                trace events. Detectors must work when it is None.
            
        Returns:
            List of dictionaries containing detected issues with keys:
            - Type: The smell type name
            - Target: The affected element (class/method name)
            - Severity: Critical/High/Medium/Low
            - Reason: Detailed explanation
            - Category: Design/Implementation/Naming/Documentation
        """
        pass
    
    def _create_issue(self, smell_type: str, target: str, severity: str,
                      reason: str, category: str, node=None) -> Dict[str, Any]:
        """
        Helper method to create a standardized issue dictionary.
        
        Args:
            smell_type: Name of the code smell
            target: Affected code element
            severity: Severity level
            reason: Detailed explanation
            category: Issue category
            node: Optional AST node the issue is attached to; its source
                position (if any) is recorded as ``Line`` so that findings
                have a stable, location-based unique key.
            
        Returns:
            Standardized issue dictionary
        """
        issue = {
            "Type": smell_type,
            "Target": target,
            "Severity": severity,
            "Reason": reason,
            "Category": category
        }
        position = getattr(node, "position", None) if node is not None else None
        issue["Line"] = position.line if position is not None else None
        return issue
