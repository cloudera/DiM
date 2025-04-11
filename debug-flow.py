import argparse
import json
import gzip
import sys
import os
from datetime import datetime
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

def load_json_file(filepath):
    if filepath.endswith('.gz'):
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            return json.load(f)
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

def save_json_file(filepath, data):
    if filepath.endswith('.gz'):
        with gzip.open(filepath, 'wt', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    else:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

def backup_file(filepath):
    now = datetime.now().strftime("%Y%m%d%H%M")
    script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    backup_name = f"{filepath}-{script_name}-{now}"
    with open(filepath, 'rb') as original:
        with open(backup_name, 'wb') as backup:
            backup.write(original.read())
    return backup_name

def walk_and_decrypt(obj):
    if isinstance(obj, dict):
        return {k: walk_and_decrypt(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [walk_and_decrypt(item) for item in obj]
    elif isinstance(obj, str):
        return "" if obj.startswith("enc{") else obj
    return obj

def extract_controller_services(data, unique, class_filter, state_filter, change_state):
    results = []
    seen = set()
    def recurse(obj):
        if isinstance(obj, dict):
            if "controllerServices" in obj:
                for cs in obj["controllerServices"]:
                    if class_filter and cs.get("type") != class_filter:
                        continue
                    if state_filter and cs.get("scheduledState") != state_filter:
                        continue
                    if change_state:
                        cs["scheduledState"] = change_state
                    iid = cs.get("instanceIdentifier")
                    if unique:
                        if iid and iid not in seen:
                            seen.add(iid)
                            results.append(iid)
                    else:
                        results.append([
                            cs.get("instanceIdentifier"),
                            cs.get("name"),
                            cs.get("type"),
                            cs.get("scheduledState")
                        ])
            for v in obj.values():
                recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
    recurse(data)
    return results

def extract_processors(group, unique, class_filter, state_filter, change_state, group_name="root"):
    results = []
    seen = set()
    for p in group.get("processors", []):
        if class_filter and p.get("type") != class_filter:
            continue
        if state_filter and p.get("scheduledState") != state_filter:
            continue
        if change_state:
            p["scheduledState"] = change_state
        iid = p.get("instanceIdentifier")
        if unique:
            if iid and iid not in seen:
                seen.add(iid)
                results.append(iid)
        else:
            results.append([
                group_name,
                p.get("name"),
                p.get("type"),
                iid,
                p.get("scheduledState"),
                "true" if p.get("validationErrors") else "false"
            ])
    for pg in group.get("processGroups", []):
        pg_name = pg.get("name", "unnamed_group")
        results += extract_processors(pg, unique, class_filter, state_filter, change_state, pg_name)
    return results

def safe_str(val):
    return str(val) if val is not None else ""

def colorize_row(row):
    if not isinstance(row, list):
        return Fore.CYAN + safe_str(row)

    if len(row) == 4:
        return "\t".join([
            Fore.CYAN + safe_str(row[0]),
            Fore.YELLOW + safe_str(row[1]),
            Fore.GREEN + safe_str(row[2]),
            Fore.BLUE + safe_str(row[3])
        ])
    elif len(row) == 6:
        group, name, type_, iid, state, errors = row
        return "\t".join([
            Fore.CYAN + safe_str(group),
            Fore.YELLOW + safe_str(name),
            Fore.GREEN + safe_str(type_),
            Fore.MAGENTA + safe_str(iid),
            Fore.BLUE + safe_str(state),
            (Fore.RED if errors == "true" else Fore.GREEN) + safe_str(errors)
        ])
    elif len(row) == 3:
        return "\t".join([
            Fore.CYAN + safe_str(row[0]),
            Fore.YELLOW + safe_str(row[1]),
            Fore.GREEN + safe_str(row[2])
        ])
    else:
        return "\t".join([safe_str(x) for x in row])

def main():
    parser = argparse.ArgumentParser(description="Parse or modify NiFi flow.json[.gz]")
    parser.add_argument("file", help="Path to flow.json or flow.json.gz")
    parser.add_argument("--processors", action="store_true", help="Extract processor info")
    parser.add_argument("--controllers", action="store_true", help="Extract controller services")
    parser.add_argument("--unique-id", action="store_true", help="Only output unique instance IDs")
    parser.add_argument("--class", dest="class_filter", help="Filter by exact processor/controller type")
    parser.add_argument("--state", dest="state_filter", help="Filter by scheduledState")
    parser.add_argument("--change-state", dest="change_state", help="Modify state for matched components")
    parser.add_argument("--decrypt", action="store_true", help="Clear enc{...} strings in-place")
    args = parser.parse_args()

    try:
        data = load_json_file(args.file)
    except Exception as e:
        print(f"{Fore.RED}❌ Error loading file: {e}")
        sys.exit(1)

    # Backup before destructive actions
    if args.decrypt or args.change_state:
        backup_path = backup_file(args.file)
        print(f"{Fore.YELLOW}📦 Backup saved to: {backup_path}")

    if args.decrypt:
        decrypted = walk_and_decrypt(data)
        save_json_file(args.file, decrypted)
        print(f"{Fore.GREEN}✅ Decrypted in-place: {args.file}")
        sys.exit(0)

    if not args.processors and not args.controllers:
        print(f"{Fore.YELLOW}⚠️  You must specify --processors or --controllers")
        sys.exit(1)

    if args.controllers:
        output = extract_controller_services(data, args.unique_id, args.class_filter, args.state_filter, args.change_state)
    else:
        output = extract_processors(data.get("rootGroup", {}), args.unique_id, args.class_filter, args.state_filter, args.change_state)

    for row in output:
        print(colorize_row(row))

    if args.change_state:
        save_json_file(args.file, data)
        print(f"\n{Fore.GREEN} State changed to '{args.change_state}' and saved to file: {args.file}")
        print(f"{Fore.YELLOW} Backup saved to: {backup_path}")

    print(f"\n{Fore.CYAN}💧 Summary")
    print(f"{Fore.GREEN}{'🆔 Unique' if args.unique_id else '📦 Total'} items found: {len(output)}")

if __name__ == "__main__":
    main()
