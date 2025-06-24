#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2024 The community Authors.
# A-Tune is licensed under the Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#     http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
# PURPOSE.
# See the Mulan PSL v2 for more details.
# Create: 2025/04/07
import psycopg2


class PgSqlClient(object):

    def __init__(self, config):
        self.config = config
        self.host = config.get('host')
        self.port = config.get('port')
        self.username = config.get('username')
        self.password = config.get('password')
        self.database = config.get('database')

    def query_data(self, query):
        conn = psycopg2.connect(
            host=self.host,
            user=self.username,
            password=self.password,
            database=self.database,
            port=self.port
        )
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def fetch_all(self, func, cursor_query, query, page_size=1000):
        last_id = None
        page = 0
        while True:
            page += 1
            print(f"Fetching page {page}...")
            last_id = self.fetch_page_by_cursor(
                func, cursor_query, query, page_size, last_id)
            if not last_id:
                print("Fetching page over.")
                break

    def fetch_page_by_cursor(self, func, cursor_query, query, page_size, last_id=None):
        try:
            conn = psycopg2.connect(
                host=self.host,
                user=self.username,
                password=self.password,
                database=self.database,
                port=self.port
            )
            cur = conn.cursor()

            # last_id 为 None，表示第一页，从最开始查询
            if last_id:
                cur.execute(cursor_query, (last_id, page_size))
            else:
                cur.execute(query, (page_size,))
            rows = cur.fetchall()
            func(rows)

            # 获取最后一条记录的 uuid，供下一次查询使用
            last_record_id = rows[-1][0] if rows else None

            # 最后一页，不需要记录最后一条记录的 uuid
            if len(rows) < page_size:
                last_record_id = None

            # 关闭游标和连接
            cur.close()
            conn.close()
            return last_record_id

        except Exception as e:
            print(f"Error: {e}")
            return None
