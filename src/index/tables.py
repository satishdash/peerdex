"""The LanceDB table a domain owns."""

from typing import Any

import lancedb

from shared.settings import get_settings, resolve_domain


class Tables:
    """Opens the LanceDB table a domain owns."""

    @staticmethod
    def open(domain: str) -> Any:
        """This domain's LanceDB table, for full-text search and row predicates.

        A domain owns its table, so the domain name *is* the table name.

        Args:
            domain: The domain, or an alias resolving to one.

        Returns:
            The open table.
        """
        s = get_settings()
        db = lancedb.connect(s.storage.lancedb_uri)
        return db.open_table(resolve_domain(domain))

    @staticmethod
    def exists(database: Any, name: str) -> bool:
        """Whether a database already holds a table under this name.

        Args:
            database: An open LanceDB connection.
            name: The table name.

        Returns:
            Whether the table is present.
        """
        return name in database.list_tables().tables
