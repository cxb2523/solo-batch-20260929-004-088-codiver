"""
Naming Convention and Documentation Smell Detectors
Validates naming standards and documentation coverage
"""

from typing import List, Dict, Any
import javalang
from detectors.base import CodeSmell, register_detector
from utils.helpers import validate_class_name, validate_method_name


@register_detector(name="naming", category="Naming", order=30,
                   config_key="naming")
class NamingSmells(CodeSmell):
    """
    Detects naming convention violations including:
    - Invalid class names (PascalCase)
    - Invalid method names (camelCase)
    - Short identifiers
    """
    
    def detect(self, tree: javalang.tree.CompilationUnit, lines: List[str],
               ctx=None) -> List[Dict[str, Any]]:
        """Detect all naming convention violations."""
        results = []
        
        # Check class naming conventions
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            class_name_ok = validate_class_name(node.name)
            if ctx is not None and not class_name_ok:
                ctx.helper_hit(
                    helper="utils.helpers.validate_class_name",
                    target=node.name,
                    result=False,
                    detail=f"PascalCase check rejected {node.name!r}",
                    line=getattr(node.position, "line", None),
                )
            if not class_name_ok:
                results.append(self._create_issue(
                    "Invalid Class Name",
                    node.name,
                    "Low",
                    "Class name should follow PascalCase convention",
                    "Naming",
                    node=node
                ))
            
            if len(node.name) < 3:
                results.append(self._create_issue(
                    "Short Name",
                    node.name,
                    "Low",
                    "Class name too short (< 3 characters)",
                    "Naming",
                    node=node
                ))
        
        # Check method naming conventions
        for _, node in tree.filter(javalang.tree.MethodDeclaration):
            method_name_ok = validate_method_name(node.name)
            if ctx is not None and not method_name_ok:
                ctx.helper_hit(
                    helper="utils.helpers.validate_method_name",
                    target=node.name,
                    result=False,
                    detail=f"camelCase check rejected {node.name!r}",
                    line=getattr(node.position, "line", None),
                )
            if not method_name_ok:
                results.append(self._create_issue(
                    "Invalid Method Name",
                    node.name,
                    "Low",
                    "Method name should follow camelCase convention",
                    "Naming",
                    node=node
                ))
            
            # Allow short common method names
            if len(node.name) < 3 and node.name not in ['is', 'do', 'to', 'of']:
                results.append(self._create_issue(
                    "Short Name",
                    node.name,
                    "Low",
                    "Method name too short (< 3 characters)",
                    "Naming",
                    node=node
                ))
        
        return results


@register_detector(name="documentation", category="Documentation",
                   order=40, config_key="documentation")
class DocumentationSmells(CodeSmell):
    """
    Detects missing or inadequate documentation including:
    - Missing class Javadoc
    - Missing public method Javadoc
    """
    
    def detect(self, tree: javalang.tree.CompilationUnit, lines: List[str],
               ctx=None) -> List[Dict[str, Any]]:
        """Detect all documentation issues."""
        results = []
        
        # Check class documentation
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            if not node.documentation:
                results.append(self._create_issue(
                    "Missing Class Documentation",
                    node.name,
                    "Low",
                    "No Javadoc found for class",
                    "Documentation",
                    node=node
                ))
        
        # Check public method documentation
        for _, node in tree.filter(javalang.tree.MethodDeclaration):
            if 'public' in (node.modifiers or []) and not node.documentation:
                results.append(self._create_issue(
                    "Missing Method Documentation",
                    node.name,
                    "Low",
                    "No Javadoc found for public method",
                    "Documentation",
                    node=node
                ))
        
        return results
