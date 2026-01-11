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

    # DEFINING RULES BY FOLDER PREFIX
    "profiles": {
        "cinematic": {
            "prefixes": ["msg_ev"],
            "max_lines": 2,
            "split_threshold_for_2": 60,
            "split_threshold_for_3": 9999, 
            "absolute_max_width": 75
        },
        "standard": {
            "prefixes": ["msg_nq", "msg_ask", "msg_tq", "msg_tlk", "msg_sq"],
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
    norm_path = file_path.replace("\\", "/")
    for prefix in CONFIG["profiles"]["cinematic"]["prefixes"]:
        if prefix in norm_path: return CONFIG["profiles"]["cinematic"]
    for prefix in CONFIG["profiles"]["standard"]["prefixes"]:
        if prefix in norm_path: return CONFIG["profiles"]["standard"]
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
    # 1. Remove the [System:Ruby...] wrappers, keep content
    # matches: rt=ANYTHING including spaces, until closing ]
    clean_text = re.sub(r'\[System:Ruby rt=.*?\](.*?)\[/System:Ruby\]', r'\1', text)
    
    # 2. (Optional Polish) If you use Zero Width Spaces (\u200B), 
    # we shouldn't count them in the length math.
    clean_text = clean_text.replace('\u200B', '') 
    
    return len(clean_text)

def tokenize_keeping_ruby_intact(text):
    """
    Splits text by spaces, but ensures spaces INSIDE ruby tags don't split the block.
    """
    # 1. Protect spaces inside Ruby tags
    def protect_match(match):
        return match.group(0).replace(' ', '<<SPACE>>')
    
    # Regex now explicitly handles the space before the closing bracket if present
    protected_text = re.sub(r'\[System:Ruby.*?\](.*?)\[/System:Ruby\]', protect_match, text)
    
    # 2. Split normally
    raw_words = protected_text.split(' ')
    
    # 3. Restore spaces in the resulting tokens
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
    
    # TOKENIZE (Ruby blocks stay as 1 item)
    words = tokenize_keeping_ruby_intact(clean_text)
    
    # ANALYZE (Count visual length only)
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

def process_single_file(file_path, log, err_log, stats):
    profile = get_profile_for_path(file_path)
    if not profile: return 

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
    parser = argparse.ArgumentParser(description="Balance text lines in JSON game files.")
    parser.add_argument("-single", help="Process only this specific file path.", default=None)
    args = parser.parse_args()

    stats = {'files_processed': 0, 'changes': 0, 'errors': 0}
    
    print("Initializing Text Balancer V8 (Ruby & Edge Case Final)...")
    
    all_prefixes = CONFIG["profiles"]["cinematic"]["prefixes"] + CONFIG["profiles"]["standard"]["prefixes"]

    with open(CONFIG["log_file"], "w", encoding="utf-8") as log, \
         open(CONFIG["error_file"], "w", encoding="utf-8") as err_log:

        if args.single:
            print(f"Mode: Single File Target -> {args.single}")
            if os.path.exists(args.single):
                if get_profile_for_path(args.single):
                    process_single_file(args.single, log, err_log, stats)
                else:
                    print(f"Skipping {args.single}: No matching profile found.")
            else:
                print(f"Error: File not found.")

        else:
            print(f"Mode: Batch Scan (Root: {CONFIG['root_directory']})")
            for root, dirs, files in os.walk(CONFIG["root_directory"]):
                if not any(os.path.basename(root).startswith(p) for p in all_prefixes):
                    continue
                for file in files:
                    if file.endswith(".json"):
                        process_single_file(os.path.join(root, file), log, err_log, stats)

    print("\nProcessing Complete.")
    print(f"Files Modified: {stats['files_processed']}")
    print(f"Text Fields Updated: {stats['changes']}")
    print(f"Overflow Errors: {stats['errors']}")

if __name__ == "__main__":
    main()
