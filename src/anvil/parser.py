import re
from typing import List, Tuple


class ResponseParser:
    @staticmethod
    def parse_edits(response: str) -> List[Tuple[str, str, str]]:
        edits = []

        pattern = r"""
            (?P<filename>[\w\-./]+\.\w+)\s*
            ```(?:\w+)?\s*
            <<<<<<< \s* SEARCH\s*
            (?P<search>.*?)
            =======\s*
            (?P<replace>.*?)
            >>>>>>> \s* REPLACE\s*
            ```
        """

        for match in re.finditer(pattern, response, re.DOTALL | re.VERBOSE):
            filename = match.group("filename")
            search = match.group("search").strip()
            replace = match.group("replace").strip()
            edits.append((filename, search, replace))

        return edits
