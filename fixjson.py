import os
import re
import datetime

# --- Configuration ---
LOG_FILENAME = "json_fix_log.txt"
TARGET_EXTENSION = ".json"

def fix_json_recursively(root_directory):
    log_entries = []
    error_entries = []
    files_changed_count = 0

    print(f"Starting recursive scan in: {root_directory}...")
    
    # 1. Recursive Walk
    for root, dirs, files in os.walk(root_directory):
        for file in files:
            if file.endswith(TARGET_EXTENSION):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # We use a list to track if specific changes happened in this file
                    file_changes = []

                    # 2. Define the callback for Regex
                    def replacement_handler(match):
                        full_match = match.group(0) # The string with quotes
                        inner_text = match.group(1) # The content inside quotes
                        
                        # Check for hard newlines (Enter key) inside the string
                        if '\n' in inner_text or '\r' in inner_text:
                            # Calculate Line Number
                            # Count newlines from start of file up to the start of this match
                            line_number = content.count('\n', 0, match.start()) + 1
                            
                            # Clean the text
                            fixed_inner = inner_text.replace('\r', '').replace('\n', '\\n')
                            
                            # Log the specific change
                            # We grab a snippet of the text for the log (first 50 chars)
                            snippet = inner_text.replace('\n', ' ' )[:50]
                            file_changes.append(f"  Line {line_number}: Fixed broken break in string starting with: \"{snippet}...\"")
                            
                            return f'"{fixed_inner}"'
                        
                        return full_match

                    # 3. Apply Regex
                    # Matches double-quoted strings, handling escaped quotes inside
                    pattern = re.compile(r'"((?:[^"\\]|\\.)*)"', re.DOTALL)
                    new_content = pattern.sub(replacement_handler, content)

                    # 4. Save file ONLY if changes occurred
                    if len(file_changes) > 0:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        
                        files_changed_count += 1
                        print(f"Fixed: {file_path}")
                        
                        # Add to main log
                        log_entries.append(f"FILE: {file_path}")
                        log_entries.extend(file_changes)
                        log_entries.append("-" * 40)

                except Exception as e:
                    print(f"ERROR reading {file_path}")
                    error_entries.append(f"ERROR: Could not process {file_path}. Reason: {str(e)}")

    # 5. Write Log File
    with open(LOG_FILENAME, 'w', encoding='utf-8') as log_file:
        log_file.write(f"Scan Date: {datetime.datetime.now()}\n")
        log_file.write(f"Root Directory: {root_directory}\n")
        log_file.write(f"Total Files Fixed: {files_changed_count}\n")
        log_file.write("=" * 60 + "\n\n")
        
        if error_entries:
            log_file.write("ERRORS:\n")
            log_file.write("\n".join(error_entries))
            log_file.write("\n\n" + "=" * 60 + "\n\n")

        if log_entries:
            log_file.write("DETAILED CHANGES:\n")
            log_file.write("\n".join(log_entries))
        else:
            log_file.write("No issues found or fixed.")

    print(f"\nProcessing Complete.")
    print(f"Fixed {files_changed_count} files.")
    print(f"Check '{LOG_FILENAME}' for details.")

if __name__ == "__main__":
    current_directory = os.getcwd()
    fix_json_recursively(current_directory)