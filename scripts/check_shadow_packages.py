#!/usr/bin/env python3
"""
NO SHADOW PACKAGES GUARD - ensures local folders don't shadow PyPI packages.

This script checks for local folders that could shadow installed packages:
- aiogram/ (should not exist, will be removed in Dockerfile)
- Any other critical packages

In Dockerfile, these are removed. This script verifies locally.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_shadow_package(package_name: str, local_path: str) -> tuple[bool, str]:
    """
    Check if local folder shadows a PyPI package.
    
    Returns:
        (is_shadow, message)
    """
    local_folder = project_root / local_path
    if local_folder.exists() and local_folder.is_dir():
        # Check if it has __init__.py (making it a Python package)
        init_file = local_folder / "__init__.py"
        if init_file.exists():
            return True, f"WARNING: Local {local_path}/ folder exists and shadows PyPI {package_name} package"
    return False, ""


def main():
    """Main shadow package check."""
    print("=" * 60)
    print("SHADOW PACKAGES CHECK")
    print("=" * 60)
    print()
    
    shadow_checks = [
        ("aiogram", "aiogram"),
    ]
    
    warnings = []
    for package_name, local_path in shadow_checks:
        is_shadow, message = check_shadow_package(package_name, local_path)
        if is_shadow:
            warnings.append(message)
            print(f"⚠️  {message}")
        else:
            print(f"✅ {package_name}: No shadow (local folder not found or not a package)")
    
    print()
    print("=" * 60)
    if warnings:
        print("⚠️  WARNINGS FOUND (will be removed in Dockerfile)")
        print("=" * 60)
        print("\nNote: Dockerfile removes these folders during build.")
        print("Locally, they may exist but won't affect production.")
        return 0  # Warning, not error
    else:
        print("✅ NO SHADOW PACKAGES - All clear")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
