"""File reader tool with resilient UTF-8 decoding."""

from __future__ import annotations

from typing import Optional

from crewai_tools import FileReadTool


class UTF8FileReadTool(FileReadTool):
    """Read text files as UTF-8, gracefully handling decode issues."""

    name: str = "Read a file's content (utf-8)"

    def _run(
        self,
        file_path: Optional[str] = None,
        start_line: Optional[int] = 1,
        line_count: Optional[int] = None,
    ) -> str:
        file_path = file_path or self.file_path
        start_line = start_line or 1
        line_count = line_count or None

        if file_path is None:
            return (
                "Error: No file path provided. Please provide a file path either in the constructor or as an argument."
            )

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                if start_line == 1 and line_count is None:
                    return handle.read()

                start_index = max(start_line - 1, 0)
                selected_lines = [
                    line
                    for idx, line in enumerate(handle)
                    if idx >= start_index and (line_count is None or idx < start_index + line_count)
                ]

                if not selected_lines and start_index > 0:
                    return f"Error: Start line {start_line} exceeds the number of lines in the file."

                return "".join(selected_lines)
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                    if start_line == 1 and line_count is None:
                        return handle.read()

                    start_index = max(start_line - 1, 0)
                    selected_lines = [
                        line
                        for idx, line in enumerate(handle)
                        if idx >= start_index and (line_count is None or idx < start_index + line_count)
                    ]

                    if not selected_lines and start_index > 0:
                        return f"Error: Start line {start_line} exceeds the number of lines in the file."

                    return "".join(selected_lines)
            except Exception as exc:
                return f"Error: Failed to read file {file_path}. {exc}"
        except FileNotFoundError:
            return f"Error: File not found at path: {file_path}"
        except PermissionError:
            return f"Error: Permission denied when trying to read file: {file_path}"
        except Exception as exc:
            return f"Error: Failed to read file {file_path}. {exc}"
