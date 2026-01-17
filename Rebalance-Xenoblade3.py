import os
import json
import argparse
import sys
import re

# ==========================================
#               CONFIGURATION
# ==========================================
CONFIG = {
    "root_directory": "UnpackedBDAT",
    "target_key": "<DBAF43F0>",
    "log_file": "text_balancing_log.txt",
    "error_file": "text_overflow_errors.txt",

    # DEFINING RULES
    "profiles": {
        "cinematic": {
            "name": "Cinematic (2-Line)",
            "prefixes": ["msg_ev"],
            "max_lines": 2,
            "split_threshold_for_2": 60,
            "split_threshold_for_3": 9999,
            "absolute_max_width": 75
        },
        "standard": {
            "name": "Standard (3-Line)",
            "prefixes": ["msg_ask", "msg_fev", "msg_tlk"],
            "max_lines": 3,
            "split_threshold_for_2": 35,
            "split_threshold_for_3": 80,
            "absolute_max_width": 55
        }
    }
}

# ==========================================
#            CORE LOGIC
# ==========================================

def get_profile_for_path(file_path):
    """
    Determines the profile based on the file path / folder name.
    1. Checks for Mixed types (msg_tq, msg_nq, etc) and looks for f/t/s suffix.
    2. Checks for Pure Standard types.
    3. Checks for Pure Cinematic types.
    """
    norm_path = file_path.replace("\\", "/")

    # 1. Mixed Category Logic (msg_nq, msg_cq, msg_tq, msg_sq)
    # We look for the pattern: msg_tq + digits + optional letter (f, t, s)
    # Regex: msg_[ncst]q followed by digits, capturing an optional trailing letter.
    mixed_match = re.search(r'(msg_[ncst]q\d+)([a-zA-Z]?)', norm_path)

    if mixed_match:
        suffix = mixed_match.group(2)
        # If there is a suffix letter (f, t, s), it's Standard (Voiced/Bubble)
        if suffix and suffix.lower() in ['f', 't', 's']:
            return CONFIG["profiles"]["standard"]
        # If no suffix (just digits), it's Cinematic (Dialogue Box)
        else:
            return CONFIG["profiles"]["cinematic"]

    # 2. Pure Standard Files (Check these BEFORE cinematic to handle msg_fev correctly vs msg_ev)
    for prefix in CONFIG["profiles"]["standard"]["prefixes"]:
        if prefix in norm_path: return CONFIG["profiles"]["standard"]

    # 3. Pure Cinematic Files
    for prefix in CONFIG["profiles"]["cinematic"]["prefixes"]:
        if prefix in norm_path: return CONFIG["profiles"]["cinematic"]

    return None

def clean_and_flatten(text):
    """Removes existing newlines and collapses multiple spaces."""
    if not text: return ""
    flat = text.replace('\n', ' ')
    flat = flat.replace('\r', '')
    return " ".join(flat.split())

def get_visual_length(text):
    """
    Calculates character count ignoring Ruby tags.
    Handles the 'rt=... ]' space correctly.
    """
    clean_text = re.sub(r'\[System:Ruby rt=.*?\](.*?)\[/System:Ruby\]', r'\1', text)
    clean_text = clean_text.replace('\u200B', '')
    return len(clean_text)

def tokenize_keeping_ruby_intact(text):
    """
    Splits text by spaces, but ensures spaces INSIDE ruby tags don't split the block.
    """
    def protect_match(match):
        return match.group(0).replace(' ', '<<SPACE>>')

    protected_text = re.sub(r'\[System:Ruby.*?\](.*?)\[/System:Ruby\]', protect_match, text)
    raw_words = protected_text.split(' ')
    words = [w.replace('<<SPACE>>', ' ') for w in raw_words if w]
    return words

def force_split(words, num_lines):
    """Strictly splits 'words' into exactly 'num_lines' based on VISUAL length."""
    if num_lines <= 1:
        return [" ".join(words)]

    total_visual_len = sum(get_visual_length(w) for w in words) + (len(words) - 1)
    target_visual_len = total_visual_len / num_lines

    lines = []
    current_words = words[:]

    for _ in range(num_lines - 1):
        best_split = 0
        best_diff = float('inf')
        current_visual_len = 0

        for i, w in enumerate(current_words):
            w_vis_len = get_visual_length(w)
            len_with = current_visual_len + w_vis_len + (1 if current_visual_len > 0 else 0)
            diff = abs(len_with - target_visual_len)

            if diff <= best_diff:
                best_diff = diff
                best_split = i + 1
                current_visual_len = len_with
            else:
                break

        lines.append(" ".join(current_words[:best_split]))
        current_words = current_words[best_split:]
        if not current_words: break

    if current_words:
        lines.append(" ".join(current_words))
    return lines

def process_text(text_content, profile):
    if not isinstance(text_content, str) or not text_content.strip():
        return text_content

    clean_text = clean_and_flatten(text_content)
    words = tokenize_keeping_ruby_intact(clean_text)
    total_len = sum(get_visual_length(w) for w in words) + (len(words) - 1)

    if total_len <= profile["split_threshold_for_2"]:
        target_lines = 1
    elif total_len <= profile["split_threshold_for_3"] and profile["max_lines"] >= 2:
        target_lines = 2
    else:
        target_lines = 3 if profile["max_lines"] >= 3 else 2

    final_lines = force_split(words, target_lines)
    return "\n".join(final_lines)

def check_for_overflow(text_block, max_width):
    lines = text_block.split('\n')
    for line in lines:
        vis_len = get_visual_length(line)
        if vis_len > max_width:
            return True, vis_len
    return False, 0

# ==========================================
#           FILE PROCESSING
# ==========================================

def process_single_file(file_path, log, err_log, stats, forced_profile=None):
    # Determine which profile to use based on the FILE NAME/PATH
    if forced_profile:
        profile = forced_profile
    else:
        profile = get_profile_for_path(file_path)

    # If no profile matches (and none forced), skip
    if not profile:
        return

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        modified = False

        if "rows" in data:
            for row in data["rows"]:
                target_key = CONFIG["target_key"]

                if target_key in row:
                    original_text = row[target_key]
                    if not original_text or original_text == "":
                        continue

                    new_text = process_text(original_text, profile)

                    is_overflow, max_len = check_for_overflow(new_text, profile["absolute_max_width"])
                    if is_overflow:
                        log_error(err_log, file_path, row.get("$id", "?"), new_text, max_len, profile["absolute_max_width"])
                        stats['errors'] += 1

                    if original_text != new_text:
                        row[target_key] = new_text
                        log_change(log, file_path, row.get("$id", "?"), original_text, new_text)
                        modified = True
                        stats['changes'] += 1

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            stats['files_processed'] += 1

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def log_change(logfile, filename, row_id, old_text, new_text):
    logfile.write(f"FILE: {filename} | ID: {row_id}\n")
    logfile.write("-" * 60 + "\n")
    vis_len = get_visual_length(clean_and_flatten(old_text))
    logfile.write(f"OLD (Vis Len: {vis_len}):\n{old_text}\n")
    logfile.write(f"\nNEW ({new_text.count(chr(10)) + 1} lines):\n{new_text}\n")
    logfile.write("-" * 60 + "\n\n")

def log_error(errfile, filename, row_id, text, max_len, limit):
    errfile.write(f"OVERFLOW: {filename} | ID: {row_id}\n")
    errfile.write(f"Visual Width: {max_len} (Limit: {limit})\n")
    errfile.write("-" * 60 + "\n")
    errfile.write(f"{text}\n")
    errfile.write("-" * 60 + "\n\n")

# ==========================================
#               MAIN ENTRY
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="""
==============================================================================
                       GAME TEXT AUTO-BALANCER TOOL
==============================================================================
This tool scans JSON files and reformats text fields <DBAF43F0> to be perfectly
balanced across lines, respecting Japanese Ruby tags and UI limits.

MODES:
1. Batch Mode: Scans 'UnpackedBDAT' automatically.
2. Single Mode: Targets one specific file (use -single).

LOGIC PROFILES:
- Standard (3-Line): Max 55 chars/line. Used for msg_fev, msg_ask, and 'Mixed' with f/t/s suffix.
- Cinematic (2-Line): Max 75 chars/line. Used for msg_ev and 'Mixed' with no suffix.

Mixed Prefixes: msg_nq, msg_cq, msg_tq, msg_sq
""",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "-single",
        metavar="FILE_PATH",
        help="Process only this specific JSON file (skips folder scanning)."
    )

    parser.add_argument(
        "-mode",
        type=int,
        choices=[2, 3],
        help="""Force a specific logic mode (Overrides folder detection):
  2 = Cinematic Mode (Max 2 lines, 75 char limit)
  3 = Standard Mode (Max 3 lines, 55 char limit)
Use this with -single to test files outside the usual folders."""
    )

    args = parser.parse_args()

    stats = {'files_processed': 0, 'changes': 0, 'errors': 0}

    # Determine if we are forcing a profile
    forced_profile = None
    if args.mode == 2:
        forced_profile = CONFIG["profiles"]["cinematic"]
        print(f"FORCED MODE: Using {forced_profile['name']} logic.")
    elif args.mode == 3:
        forced_profile = CONFIG["profiles"]["standard"]
        print(f"FORCED MODE: Using {forced_profile['name']} logic.")

    print("\nStarting Text Balancer...")

    # We only need specific prefixes for scanning optimization,
    # but the logic inside get_profile_for_path handles the details.
    # We include mixed prefixes (msg_nq, msg_tq etc) in the scan list.
    mixed_prefixes = ["msg_nq", "msg_cq", "msg_tq", "msg_sq"]
    all_prefixes = (CONFIG["profiles"]["cinematic"]["prefixes"] +
                    CONFIG["profiles"]["standard"]["prefixes"] +
                    mixed_prefixes)

    with open(CONFIG["log_file"], "w", encoding="utf-8") as log, \
         open(CONFIG["error_file"], "w", encoding="utf-8") as err_log:

        # CASE 1: Single File Mode
        if args.single:
            print(f"Targeting Single File: {args.single}")
            if os.path.exists(args.single):
                if forced_profile or get_profile_for_path(args.single):
                    process_single_file(args.single, log, err_log, stats, forced_profile)
                else:
                    print(f"Skipping {args.single}: Path does not match known prefixes.")
                    print("Tip: Use -mode 2 or -mode 3 to force processing.")
            else:
                print(f"Error: File not found -> {args.single}")

        # CASE 2: Batch Directory Mode
        else:
            print(f"Scanning Directory: {CONFIG['root_directory']}")
            for root, dirs, files in os.walk(CONFIG["root_directory"]):
                # Optimization: Only enter folders that start with known prefixes
                if not any(os.path.basename(root).startswith(p) for p in all_prefixes):
                    continue

                for file in files:
                    if file.endswith(".json"):
                        process_single_file(os.path.join(root, file), log, err_log, stats, forced_profile)

    print("\n" + "="*40)
    print(f"Processing Complete.")
    print(f"Files Modified:    {stats['files_processed']}")
    print(f"Text Rows Updated: {stats['changes']}")
    print(f"Overflow Errors:   {stats['errors']}")
    print(f"Logs saved to:     {CONFIG['log_file']}")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()
