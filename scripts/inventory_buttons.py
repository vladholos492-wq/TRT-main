#!/usr/bin/env python3
"""
Button Inventory - полная инвентаризация всех кнопок в боте.

Находит все InlineKeyboardButton, KeyboardButton, callback_data паттерны,
строит карту кнопок и выводит JSON + Markdown отчёт.
"""
import sys
import os
import re
import json
import ast
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def extract_callback_data_from_code(content: str, file_path: Path) -> List[Dict[str, Any]]:
    """
    Extract all callback_data from code using AST and regex.
    
    Returns list of dicts with: button_text, callback_data, line_number, context
    """
    buttons = []
    
    # Pattern 1: InlineKeyboardButton(text="...", callback_data="...")
    pattern1 = re.compile(
        r'InlineKeyboardButton\s*\(\s*[^,]*text\s*=\s*["\']([^"\']+)["\'][^)]*callback_data\s*=\s*["\']([^"\']+)["\']',
        re.MULTILINE | re.DOTALL
    )
    
    # Pattern 2: callback_data="..." (standalone)
    pattern2 = re.compile(
        r'callback_data\s*=\s*["\']([^"\']+)["\']',
        re.MULTILINE
    )
    
    # Pattern 3: f-strings with callback_data
    pattern3 = re.compile(
        r'callback_data\s*=\s*f["\']([^"\']*)\{([^}]+)\}([^"\']*)["\']',
        re.MULTILINE
    )
    
    lines = content.split('\n')
    
    # Find all InlineKeyboardButton instances
    for i, line in enumerate(lines, 1):
        # Pattern 1: Full button definition
        for match in pattern1.finditer(line):
            text = match.group(1)
            callback_data = match.group(2)
            buttons.append({
                "button_text": text,
                "callback_data": callback_data,
                "line_number": i,
                "file": str(file_path),
                "type": "inline",
                "context": "button_definition"
            })
        
        # Pattern 2: Standalone callback_data
        for match in pattern2.finditer(line):
            callback_data = match.group(1)
            # Try to find button text from context
            text = None
            # Look for text= in nearby lines
            for j in range(max(0, i-3), min(len(lines), i+3)):
                text_match = re.search(r'text\s*=\s*["\']([^"\']+)["\']', lines[j])
                if text_match:
                    text = text_match.group(1)
                    break
            
            buttons.append({
                "button_text": text or "N/A",
                "callback_data": callback_data,
                "line_number": i,
                "file": str(file_path),
                "type": "inline",
                "context": "callback_data_only"
            })
        
        # Pattern 3: f-strings (dynamic callback_data)
        for match in pattern3.finditer(line):
            prefix = match.group(1)
            var = match.group(2)
            suffix = match.group(3)
            # Build pattern like "prefix:{var}suffix"
            callback_pattern = f"{prefix}{{{var}}}{suffix}"
            buttons.append({
                "button_text": "N/A (dynamic)",
                "callback_data": callback_pattern,
                "line_number": i,
                "file": str(file_path),
                "type": "inline",
                "context": "f_string_pattern",
                "is_pattern": True
            })
    
    return buttons


def extract_handler_patterns(content: str, file_path: Path) -> List[Dict[str, Any]]:
    """
    Extract handler patterns from router decorators.
    
    Returns list of dicts with: callback_data_pattern, handler_name, line_number
    """
    handlers = []
    
    # Pattern 1: @router.callback_query(F.data == "something")
    pattern1 = re.compile(
        r'@router\.callback_query\s*\([^)]*F\.data\s*==\s*["\']([^"\']+)["\']',
        re.MULTILINE
    )
    
    # Pattern 2: @router.callback_query(F.data.startswith("something"))
    pattern2 = re.compile(
        r'@router\.callback_query\s*\([^)]*F\.data\.startswith\s*\(["\']([^"\']+)["\']',
        re.MULTILINE
    )
    
    # Pattern 3: @router.callback_query(F.data.in_([...]))
    pattern3 = re.compile(
        r'@router\.callback_query\s*\([^)]*F\.data\.in_\s*\(\[([^\]]+)\]',
        re.MULTILINE
    )
    
    # Pattern 4: @router.callback_query(F.data.in_({"key1", "key2"}))
    pattern4 = re.compile(
        r'@router\.callback_query\s*\([^)]*F\.data\.in_\s*\(\{([^\}]+)\}',
        re.MULTILINE
    )
    
    # Pattern 5: Function definition after decorator
    func_pattern = re.compile(
        r'async def (\w+)\s*\([^)]*callback[^)]*\)',
        re.MULTILINE
    )
    
    lines = content.split('\n')
    
    for i, line in enumerate(lines, 1):
        # Check for exact match
        match1 = pattern1.search(line)
        if match1:
            callback_data = match1.group(1)
            # Find handler name (next function definition)
            for j in range(i, min(len(lines), i+10)):
                func_match = func_pattern.search(lines[j])
                if func_match:
                    handlers.append({
                        "callback_data_pattern": callback_data,
                        "handler_name": func_match.group(1),
                        "line_number": i,
                        "file": str(file_path),
                        "match_type": "exact"
                    })
                    break
        
        # Check for startswith
        match2 = pattern2.search(line)
        if match2:
            prefix = match2.group(1)
            # Find handler name
            for j in range(i, min(len(lines), i+10)):
                func_match = func_pattern.search(lines[j])
                if func_match:
                    handlers.append({
                        "callback_data_pattern": f"{prefix}*",
                        "handler_name": func_match.group(1),
                        "line_number": i,
                        "file": str(file_path),
                        "match_type": "prefix"
                    })
                    break
        
        # Check for in_ list
        match3 = pattern3.search(line)
        if match3:
            items_str = match3.group(1)
            # Parse items (simple, may need improvement)
            items = re.findall(r'["\']([^"\']+)["\']', items_str)
            for item in items:
                # Find handler name
                for j in range(i, min(len(lines), i+10)):
                    func_match = func_pattern.search(lines[j])
                    if func_match:
                        handlers.append({
                            "callback_data_pattern": item,
                            "handler_name": func_match.group(1),
                            "line_number": i,
                            "file": str(file_path),
                            "match_type": "in_list"
                        })
                        break
        
        # Check for in_ set (F.data.in_({"key1", "key2"}))
        match4 = pattern4.search(line)
        if match4:
            items_str = match4.group(1)
            # Parse items from set
            items = re.findall(r'["\']([^"\']+)["\']', items_str)
            for item in items:
                # Find handler name
                for j in range(i, min(len(lines), i+10)):
                    func_match = func_pattern.search(lines[j])
                    if func_match:
                        handlers.append({
                            "callback_data_pattern": item,
                            "handler_name": func_match.group(1),
                            "line_number": i,
                            "file": str(file_path),
                            "match_type": "in_set"
                        })
                        break
    
    return handlers


def scan_handlers_directory() -> Tuple[Dict[str, List[Dict]], Dict[str, List[Dict]]]:
    """
    Scan bot/handlers directory for all buttons and handlers.
    
    Returns:
        (buttons_dict, handlers_dict)
        buttons_dict: file -> list of buttons
        handlers_dict: file -> list of handlers
    """
    handlers_dir = project_root / "bot" / "handlers"
    buttons_dict = defaultdict(list)
    handlers_dict = defaultdict(list)
    
    if not handlers_dir.exists():
        print(f"Warning: {handlers_dir} does not exist")
        return buttons_dict, handlers_dict
    
    for py_file in handlers_dir.glob("*.py"):
        if py_file.name.startswith("__"):
            continue
        
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            buttons = extract_callback_data_from_code(content, py_file)
            handlers = extract_handler_patterns(content, py_file)
            
            if buttons:
                buttons_dict[str(py_file)] = buttons
            if handlers:
                handlers_dict[str(py_file)] = handlers
        
        except Exception as e:
            print(f"Error processing {py_file}: {e}")
    
    return buttons_dict, handlers_dict


def build_button_map(buttons_dict: Dict, handlers_dict: Dict) -> Dict[str, Any]:
    """
    Build a map of screens/contexts to buttons.
    
    Returns structured dict with:
    - screens: screen_id -> list of buttons
    - buttons_by_callback: callback_data -> button info
    - handlers_by_callback: callback_data -> handler info
    - coverage: which buttons have handlers
    """
    button_map = {
        "screens": defaultdict(list),
        "buttons_by_callback": {},
        "handlers_by_callback": {},
        "coverage": {
            "total_buttons": 0,
            "buttons_with_handlers": 0,
            "buttons_without_handlers": [],
            "handlers_without_buttons": []
        }
    }
    
    # Collect all buttons
    all_buttons = []
    for file, buttons in buttons_dict.items():
        for button in buttons:
            callback_data = button["callback_data"]
            all_buttons.append(button)
            button_map["buttons_by_callback"][callback_data] = button
            
            # Try to infer screen from callback_data prefix
            if ":" in callback_data:
                prefix = callback_data.split(":")[0]
                screen_id = f"{prefix}_screen"
            else:
                screen_id = "main_screen"
            
            button_map["screens"][screen_id].append({
                "text": button["button_text"],
                "callback_data": callback_data,
                "file": file
            })
    
    # Collect all handlers
    all_handlers = []
    for file, handlers in handlers_dict.items():
        for handler in handlers:
            pattern = handler["callback_data_pattern"]
            all_handlers.append(handler)
            button_map["handlers_by_callback"][pattern] = handler
    
    # Calculate coverage
    button_map["coverage"]["total_buttons"] = len(all_buttons)
    
    for callback_data in button_map["buttons_by_callback"]:
        has_handler = False
        for pattern in button_map["handlers_by_callback"]:
            if pattern == callback_data or (pattern.endswith("*") and callback_data.startswith(pattern[:-1])):
                has_handler = True
                break
        
        if has_handler:
            button_map["coverage"]["buttons_with_handlers"] += 1
        else:
            button_map["coverage"]["buttons_without_handlers"].append(callback_data)
    
    # Find handlers without buttons
    for pattern in button_map["handlers_by_callback"]:
        has_button = False
        for callback_data in button_map["buttons_by_callback"]:
            if pattern == callback_data or (pattern.endswith("*") and callback_data.startswith(pattern[:-1])):
                has_button = True
                break
        
        if not has_button:
            button_map["coverage"]["handlers_without_buttons"].append(pattern)
    
    return button_map


def generate_markdown_report(button_map: Dict, output_path: Path):
    """Generate Markdown report from button map."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Button Inventory Report\n\n")
        f.write(f"**Generated**: {Path(__file__).stat().st_mtime}\n\n")
        
        # Coverage summary
        coverage = button_map["coverage"]
        f.write("## Coverage Summary\n\n")
        f.write(f"- **Total Buttons**: {coverage['total_buttons']}\n")
        f.write(f"- **Buttons with Handlers**: {coverage['buttons_with_handlers']}\n")
        f.write(f"- **Buttons without Handlers**: {len(coverage['buttons_without_handlers'])}\n")
        f.write(f"- **Handlers without Buttons**: {len(coverage['handlers_without_buttons'])}\n\n")
        
        # Buttons by screen
        f.write("## Buttons by Screen\n\n")
        for screen_id, buttons in sorted(button_map["screens"].items()):
            f.write(f"### {screen_id}\n\n")
            for button in buttons:
                f.write(f"- `{button['callback_data']}` - {button['text']}\n")
            f.write("\n")
        
        # Buttons without handlers
        if coverage["buttons_without_handlers"]:
            f.write("## WARNING: Buttons Without Handlers\n\n")
            for callback_data in coverage["buttons_without_handlers"]:
                button = button_map["buttons_by_callback"].get(callback_data, {})
                f.write(f"- `{callback_data}` - {button.get('button_text', 'N/A')} (file: {button.get('file', 'N/A')})\n")
            f.write("\n")
        
        # Handlers without buttons
        if coverage["handlers_without_buttons"]:
            f.write("## WARNING: Handlers Without Buttons\n\n")
            for pattern in coverage["handlers_without_buttons"]:
                handler = button_map["handlers_by_callback"].get(pattern, {})
                f.write(f"- `{pattern}` - {handler.get('handler_name', 'N/A')} (file: {handler.get('file', 'N/A')})\n")
            f.write("\n")


def main():
    """Main function."""
    print("=" * 60)
    print("BUTTON INVENTORY")
    print("=" * 60)
    print()
    
    # Scan handlers
    print("Scanning bot/handlers directory...")
    buttons_dict, handlers_dict = scan_handlers_directory()
    
    print(f"Found {sum(len(b) for b in buttons_dict.values())} buttons")
    print(f"Found {sum(len(h) for h in handlers_dict.values())} handlers")
    print()
    
    # Build button map
    print("Building button map...")
    button_map = build_button_map(buttons_dict, handlers_dict)
    
    # Create artifacts directory
    artifacts_dir = project_root / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    
    # Save JSON
    json_path = artifacts_dir / "buttons_inventory.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(button_map, f, indent=2, ensure_ascii=False)
    print(f"[OK] JSON saved: {json_path}")
    
    # Generate Markdown
    md_path = artifacts_dir / "buttons_inventory.md"
    generate_markdown_report(button_map, md_path)
    print(f"[OK] Markdown saved: {md_path}")
    
    # Print summary
    coverage = button_map["coverage"]
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total Buttons: {coverage['total_buttons']}")
    print(f"Buttons with Handlers: {coverage['buttons_with_handlers']}")
    print(f"Buttons without Handlers: {len(coverage['buttons_without_handlers'])}")
    print(f"Handlers without Buttons: {len(coverage['handlers_without_buttons'])}")
    
    if coverage["buttons_without_handlers"]:
        print("\n[WARNING] Buttons without handlers:")
        for callback_data in coverage["buttons_without_handlers"][:10]:
            print(f"   - {callback_data}")
        if len(coverage["buttons_without_handlers"]) > 10:
            print(f"   ... and {len(coverage['buttons_without_handlers']) - 10} more")
    
    print()
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

