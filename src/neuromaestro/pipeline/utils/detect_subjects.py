import os
import sys
from typing import List

def detect_subjects(input_dir: str, prefix: str = "sub-") -> List[str]:
    """
    Detect subjects in a directory based on prefix
    
    Args:
        input_dir: Input directory path
        prefix: Subject prefix (default: "sub-")
        
    Returns:
        List of subject IDs (without prefix)
    """
    if not os.path.isdir(input_dir):
        return []

    subjects = []
    for name in os.listdir(input_dir):
        full_path = os.path.join(input_dir, name)

        if not os.path.isdir(full_path):
            continue

        if prefix == "":
            subjects.append(name)
            continue

        if name.startswith(prefix):
            subject_id = name[len(prefix):]
            if subject_id:
                subjects.append(subject_id)

    
    subjects.sort()
    return subjects


def parse_subjects_input(subjects: str) -> List[str]:
    """Parse a subject list from a string or file path.

    Accepts a comma-separated string, a newline-separated file, or a
    comma-separated file. Returns a list of stripped, non-empty subject IDs.
    """
    subjects_path = os.path.join(subjects)
    if os.path.isfile(subjects_path):
        with open(subjects_path) as f:
            subjects = f.read().strip()
    subjects = subjects.replace("\n", ",").replace("\r", "")
    return [s.strip() for s in subjects.split(",") if s.strip()]


def save_subjects_to_file(subjects: List[str], output_file: str) -> None:
    """Save subjects to file (comma-separated)"""
    output_dir = os.path.dirname(output_file)
    if output_dir and output_dir != ".":
        os.makedirs(output_dir, exist_ok=True)

    with open(output_file, "w") as f:
        f.write(",".join(subjects) if subjects else "")


def show_help():
    print("Usage: detect_subjects <input_dir> <output_file> [prefix]")
    print("")
    print("Examples:")
    print("  detect_subjects /data/raw subjects.txt")
    print("  detect_subjects /data/raw subjects.txt sub-")
    print("")
    print("Parameters:")
    print("  input_dir   - Input directory path")
    print("  output_file - Output file path")
    print("  prefix      - Folder prefix (default: sub-)")


def main():
    """Command line interface"""
    args = sys.argv[1:]

    if len(args) < 2 or args[0] in ["-h", "--help"]:
        show_help()
        sys.exit(0 if args and args[0] in ["-h", "--help"] else 1)

    input_dir = args[0]
    output_file = args[1]
    prefix = args[2] if len(args) > 2 else "sub-"

    if not os.path.isdir(input_dir):
        print(f"Error: Input directory does not exist: {input_dir}")
        sys.exit(1)

    subjects = detect_subjects(input_dir, prefix)
    
    save_subjects_to_file(subjects, output_file)
    
    if subjects:
        print(f"Success: Detected {len(subjects)} subjects")
        print(f"Saved to: {output_file}")
        print(f"Subjects: {', '.join(subjects)}")
    else:
        print(f"No subjects found with prefix: {prefix}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()