#!/usr/bin/env python3
"""
Lint UX strings - ищет "user-facing english" по простым эвристикам.

Валит, если находит английские строки в user-facing местах (await message.answer, await callback.message.edit_text).
"""
import sys
import re
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def find_user_facing_strings(file_path: Path) -> list:
    """Find user-facing strings in Python file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern: await message.answer("...") or await callback.message.edit_text("...")
    patterns = [
        r'await\s+(?:message|callback\.message)\.(?:answer|edit_text|reply)\s*\(\s*["\']([^"\']+)["\']',
        r'await\s+(?:message|callback\.message)\.(?:answer|edit_text|reply)\s*\(\s*f["\']([^"\']+)["\']',
    ]
    
    matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            matches.append((match.group(1), match.start(), match.end()))
    
    return matches


def is_english_text(text: str) -> bool:
    """Check if text is English (simple heuristic)."""
    # Check for common English words
    english_words = [
        'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but', 'not', 'this', 'that',
        'with', 'from', 'for', 'you', 'your', 'error', 'success', 'failed', 'please',
        'try', 'again', 'click', 'select', 'choose', 'enter', 'input', 'output'
    ]
    
    text_lower = text.lower()
    english_word_count = sum(1 for word in english_words if word in text_lower)
    
    # If more than 2 English words, likely English
    if english_word_count > 2:
        return True
    
    # Check for Cyrillic characters
    cyrillic_pattern = re.compile(r'[А-Яа-яЁё]')
    has_cyrillic = bool(cyrillic_pattern.search(text))
    
    # If no Cyrillic and has English words, likely English
    if not has_cyrillic and english_word_count > 0:
        return True
    
    return False


def lint_file(file_path: Path) -> list:
    """Lint a single file for English user-facing strings."""
    issues = []
    
    try:
        strings = find_user_facing_strings(file_path)
        for text, start, end in strings:
            # Skip very short strings (likely variables)
            if len(text) < 5:
                continue
            
            # Skip if contains only symbols/numbers
            if re.match(r'^[\d\s\W]+$', text):
                continue
            
            # Check if English
            if is_english_text(text):
                issues.append({
                    "file": str(file_path),
                    "text": text[:100],
                    "position": (start, end)
                })
    except Exception as e:
        issues.append({
            "file": str(file_path),
            "error": str(e)
        })
    
    return issues


def main():
    """Main lint function."""
    print("=" * 60)
    print("LINT UX STRINGS")
    print("=" * 60)
    print()
    
    handlers_dir = project_root / "bot" / "handlers"
    all_issues = []
    
    for py_file in handlers_dir.glob("*.py"):
        if py_file.name.startswith("__"):
            continue
        
        issues = lint_file(py_file)
        if issues:
            all_issues.extend(issues)
            print(f"[WARNING] {py_file.name}: {len(issues)} potential English strings")
            for issue in issues[:3]:  # Show first 3
                if "error" in issue:
                    print(f"  Error: {issue['error']}")
                else:
                    print(f"  '{issue['text']}'")
            if len(issues) > 3:
                print(f"  ... and {len(issues) - 3} more")
    
    print()
    print("=" * 60)
    if all_issues:
        print(f"[FAIL] Found {len(all_issues)} potential English user-facing strings")
        print("=" * 60)
        return 1
    else:
        print("[PASS] No English user-facing strings found")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())

