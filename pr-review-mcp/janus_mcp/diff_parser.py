def parse_diff(raw: str) -> dict:
    files = []
    current_file = None
    current_hunk = None
    old_line = 0
    new_line = 0

    for line in raw.splitlines():
        if line.startswith("diff --git"):
            if current_file:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            current_file = {"filename": "", "hunks": []}
            current_hunk = None

        elif line.startswith("--- "):
            pass  # handled by +++ line

        elif line.startswith("+++ ") and current_file is not None:
            name = line[4:]
            if name.startswith("b/"):
                name = name[2:]
            current_file["filename"] = name

        elif line.startswith("@@ ") and current_file is not None:
            if current_hunk:
                current_file["hunks"].append(current_hunk)
            parts = line.split(" ")
            old_part = parts[1]  # e.g. -10,5
            new_part = parts[2]  # e.g. +10,6
            old_line = abs(int(old_part.split(",")[0]))
            new_line = abs(int(new_part.split(",")[0]))
            current_hunk = {"header": line, "lines": []}

        elif current_hunk is not None:
            if line.startswith("+"):
                current_hunk["lines"].append({
                    "type": "add", "content": line[1:],
                    "old_line": None, "new_line": new_line
                })
                new_line += 1
            elif line.startswith("-"):
                current_hunk["lines"].append({
                    "type": "remove", "content": line[1:],
                    "old_line": old_line, "new_line": None
                })
                old_line += 1
            elif line.startswith("\\"):
                pass  # "No newline at end of file"
            else:
                current_hunk["lines"].append({
                    "type": "context", "content": line[1:],
                    "old_line": old_line, "new_line": new_line
                })
                old_line += 1
                new_line += 1

    if current_file:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    return {"files": files}
