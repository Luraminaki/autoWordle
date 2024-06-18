#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun 18 11:43:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect
import pathlib
import sqlite3

from threading import Lock
from typing import Any

#pylint: disable=wrong-import-position, wrong-import-order

#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def try_process_to_str_or_null_str(val: None | str | Any) -> str:
    curr_func = inspect.currentframe().f_code.co_name

    if isinstance(val, str):
        return f"'{val}'"

    if val is None:
        return 'NULL'

    try:
        return str(val)

    except Exception as err:
        print(f"{curr_func} -- Provided value cannot be cast to str: {repr(err)}")
        return 'NULL'


class CacheDB:
    def __init__(self, db_file_path: str | pathlib.Path, table_names: set[str] | set[int] | set[tuple[int]]=None, **kwargs: str) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        self.db_path = str(db_file_path)
        self.table_names = table_names

        self.columns = {
            '__pkid': 'INTEGER PRIMARY KEY',
        }
        self.columns.update({k.lower(): v.upper() for (k,v) in kwargs.items()})

        self.lock = Lock()
        self.db = sqlite3.connect(self.db_path, timeout=3.0, isolation_level=None, check_same_thread=False)

        if self.table_names is not None:
            try:
                with self.lock:
                    with self.db:
                        if all(not self._check_table(table_name) for table_name in self.table_names):
                            print(f"{curr_func} -- Either database is corrupted or newly created...")

                        for table_name in self.table_names:
                            self._create_table(table_name)

            except Exception as err:
                print(f"{curr_func} -- Failed to create db: {repr(err)}")


    def _is_valid_column(self, col: str) -> bool:
        return col.lower() in self.columns or col=='*'


    def _check_table(self, table_name: str | int | tuple[int]) -> bool:
        curr_func = inspect.currentframe().f_code.co_name

        if isinstance(table_name, tuple):
            table_name = "".join(str(letter) for letter in table_name)
        else:
            table_name = str(table_name)

        try:
            # https://docs.python.org/3/library/sqlite3.html#sqlite3-howto-row-factory
            self.db.row_factory = sqlite3.Row
            fields_info = list((row['name'], row['type']) for row in self.db.execute(f'PRAGMA table_info("{table_name}")'))

            # https://stackoverflow.com/questions/70148120/reset-row-factory-attribute-of-an-python-sqlite3-object
            self.db.row_factory = None

        except Exception as err:
            self.db.row_factory = None
            print(f"{curr_func} -- Failed to check table {table_name}: {repr(err)}")
            return False

        if fields_info:
            return all((key, val.split(' ', maxsplit=1)[0]) in fields_info for (key, val) in self.columns.items())

        print(f"{curr_func} -- table {table_name} failed PRAGMA table_info query")
        return False


    def _check_table_exists(self, table_name: str | int | tuple[int]) -> bool:
        curr_func = inspect.currentframe().f_code.co_name

        if isinstance(table_name, tuple):
            table_name = "".join(str(letter) for letter in table_name)
        else:
            table_name = str(table_name)

        try:
            with self.lock:
                # https://docs.python.org/3/library/sqlite3.html#sqlite3-howto-row-factory
                self.db.row_factory = sqlite3.Row
                with self.db:
                    cursor: list[sqlite3.Row] = list(self.db.execute('SELECT name FROM sqlite_master WHERE type="table"'))

                # https://stackoverflow.com/questions/70148120/reset-row-factory-attribute-of-an-python-sqlite3-object
                self.db.row_factory = None
                return table_name in [ row[key] for row in cursor for key in row.keys() ]

        except Exception as err:
            print(f"{curr_func} -- Failed to check if {table_name} table exists: {repr(err)}")
            return False


    def _create_table(self, table_name: str | int | tuple[int]) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        data_types = tuple('{} {}'.format(key, val if val.split(' ', maxsplit=1)[0] in ('INTEGER', 'REAL', 'TEXT', 'BLOB') else 'TEXT') for (key, val) in self.columns.items())

        if isinstance(table_name, tuple):
            table_name = "".join(str(letter) for letter in table_name)
        else:
            table_name = str(table_name)

        # print(f"{curr_func} -- Creating table {table_name} with dtypes {data_types}")

        try:
            self.db.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(data_types)})')

        except Exception as err:
            print(f"{curr_func} -- Failed to CREATE TABLE {table_name}: {repr(err)}")
            raise err


    def _format_where(self, cond: dict[str, int | float | str], operator: str="AND") -> str:
        if (pkid_val := cond.get('__pkid', None)) is not None:
            return f"__pkid={pkid_val}"

        result = f' {operator} '.join(f'{key} IS NULL' if value is None else f'{key}={try_process_to_str_or_null_str(value)}' for key, value in cond.items() if key in self.columns)

        if not result:
            # https://www.navicat.com/en/company/aboutus/blog/1812-the-purpose-of-where-1-1-in-sql-statements
            result = '1=1'

        return result


    def add_entries(self, table_name: str | int | tuple[int], **kwargs: list[str]) -> bool:
        curr_func = inspect.currentframe().f_code.co_name

        if isinstance(table_name, tuple):
            table_name = "".join(str(letter) for letter in table_name)
        else:
            table_name = str(table_name)

        if not self._check_table_exists(table_name):
            return False

        for (key, value) in kwargs.items():
            if key not in self.columns:
                return False

            if not isinstance(value, list):
                return False

        datas: list[dict[str, str]] = [dict(zip(kwargs, value)) for value in zip(*kwargs.values())]

        if not datas:
            print(f"{curr_func} -- Failed to INSERT {table_name} empty entry")
            return False

        # print(f"{curr_func} -- Adding entry {data} to {table_name}")

        try:
            with self.lock:
                with self.db:
                    try:
                        self.db.execute("PRAGMA synchronous = OFF")
                        self.db.execute("PRAGMA journal_mode = OFF")
                        for entry in datas:
                            data = { key: try_process_to_str_or_null_str(value) for (key, value) in entry.items() if key in self.columns }
                            self.db.execute(f'INSERT INTO "{table_name}" ({", ".join(data.keys())}) VALUES ({", ".join(data.values())})')

                    except Exception as err:
                        print(f"{curr_func} -- Failed to INSERT {table_name} entry with {data}: {repr(err)}")

        except Exception as err:
            print(f"{curr_func} -- Failed to INSERT {table_name} entry with {datas}: {repr(err)}")
            return False

        return True


    def get_entries(self, table_name: str | int | tuple[int], columns: set[str] | tuple[str]=(), constraints: str="", **kwargs) -> list[dict[str, int | float | str]]:
        curr_func = inspect.currentframe().f_code.co_name

        if isinstance(table_name, tuple):
            table_name = "".join(str(letter) for letter in table_name)
        else:
            table_name = str(table_name)

        if not self._check_table_exists(table_name):
            return False

        cols = ','.join(col for col in columns if self._is_valid_column(col))
        if not cols:
            cols = '*'

        cond = self._format_where(kwargs)

        # https://sqlbolt.com/lesson/select_queries_with_constraints
        if constraints:
            cond = cond + ' ' + constraints

        # print(f"{curr_func} -- Selecting from {table_name} with args {kwargs}")

        try:
            with self.lock:
                # https://docs.python.org/3/library/sqlite3.html#sqlite3-howto-row-factory
                self.db.row_factory = sqlite3.Row
                with self.db:
                    cursor: list[sqlite3.Row] = list(self.db.execute(f'SELECT {cols} FROM "{table_name}" WHERE {cond}'))

                # https://stackoverflow.com/questions/70148120/reset-row-factory-attribute-of-an-python-sqlite3-object
                self.db.row_factory = None

        except Exception as err:
            self.db.row_factory = None
            print(f"{curr_func} -- Failed to SELECT {cols} FROM {table_name} WHERE {cond}: {repr(err)}")
            return []

        return [ { key: row[key] for key in row.keys() } for row in cursor ]
