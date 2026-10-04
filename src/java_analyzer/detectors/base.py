"""
Abstract Base Class for Code Smell Detectors
Defines the contract that all detector implementations must follow
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Type
import javalang


# Centralized detector registry.
#
# Decision: detectors are registered explicitly in one ordered list
# (populated by analyzer_engine at import time) instead of decorator-based
# auto-discovery. Auto-discovery depends on module import order, which is
# fragile and hard to review; an explicit registry makes execution order a
# testable constant.
#
# Registration order DOES determine the order of issues in the raw result
# list (detectors run sequentially and issues are appended in order), but
# it does NOT change deduplication results: dedup keys are content-based
# (see traceability.issue_key), so the set of unique issues and every
# per-file / per-rule count is order-invariant.
DETECTOR_REGISTRY: List[Tuple[str, Type["CodeSmell"]]] = []


def register_detector(config_key: str, detector_cls: Type["CodeSmell"]) -> None:
    """
    Register a detector class under its configuration key.

    Args:
        config_key: Key used in the analysis config dict (e.g. 'design')
        detector_cls: CodeSmell subclass to instantiate when enabled

    Raises:
        ValueError: If the config key is already registered
    """
    if any(key == config_key for key, _ in DETECTOR_REGISTRY):
        raise ValueError(f"Duplicate detector registration: {config_key}")
    DETECTOR_REGISTRY.append((config_key, detector_cls))


def build_detectors(config: Dict[str, bool] = None) -> List["CodeSmell"]:
    """
    Instantiate enabled detectors in registry order.

    Args:
        config: Dictionary mapping config keys to enabled flags.
                Missing keys default to enabled.

    Returns:
        List of detector instances in deterministic registry order
    """
    config = config or {}
    return [cls() for key, cls in DETECTOR_REGISTRY if config.get(key, True)]


class CodeSmell(ABC):
    """
    Abstract base class for all code smell detectors.
    Implements the Strategy Pattern for different detection algorithms.
    """
    
    @abstractmethod
    def detect(self, tree: javalang.tree.CompilationUnit, lines: List[str]) -> List[Dict[str, Any]]:
        """
        Detect code smells in the given AST tree.
        
        Args:
            tree: Parsed Java AST (Abstract Syntax Tree)
            lines: Source code split into lines
            
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
                      reason: str, category: str) -> Dict[str, Any]:
        """
        Helper method to create a standardized issue dictionary.
        
        Args:
            smell_type: Name of the code smell
            target: Affected code element
            severity: Severity level
            reason: Detailed explanation
            category: Issue category
            
        Returns:
            Standardized issue dictionary
        """
        return {
            "Type": smell_type,
            "Target": target,
            "Severity": severity,
            "Reason": reason,
            "Category": category
        }
