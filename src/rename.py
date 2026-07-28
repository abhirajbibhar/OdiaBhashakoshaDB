import os
import argparse

def rename_files(extension_from, extension_to, directory="."):
    for filename in os.listdir(directory):
        if filename.endswith(extension_from):
            base = os.path.splitext(filename)[0]
            new_name = base + extension_to
            os.rename(os.path.join(directory, filename), os.path.join(directory, new_name))
            print(f"Renamed: {filename} -> {new_name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rename .txt files to .csv and vice versa")
    parser.add_argument("action", choices=["to_csv", "to_txt"], help="Choose rename direction")
    parser.add_argument("--dir", default=".", help="Directory containing files (default: current dir)")
    args = parser.parse_args()

    if args.action == "to_csv":
        rename_files(".txt", ".csv", args.dir)
    elif args.action == "to_txt":
        rename_files(".csv", ".txt", args.dir)
