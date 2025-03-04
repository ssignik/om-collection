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
# Create: 2024/7/15
import json
import datetime

from collect.my_sql import MySqlClient
from data.common import ESClient


class VersionDownload(object):

    def __init__(self, config):
        self.config = config
        self.index_name = config.get('index_name')
        self.query_index_name = config.get('query_index_name')
        self.url = config.get('es_url')
        self.authorization = config.get('authorization')
        self.esClient = ESClient(config)
        self.my_client = MySqlClient(config)
        self.table = config.get('table')
        self.before_days = config.get('before_days', 1)
        self.user_info = {}

    def run(self, start):
        start_date = str(datetime.date.today() + datetime.timedelta(days=-int(self.before_days)))
        print('start collect version download data from ', start_date)
        self.user_info = self.get_user_info()
        self.get_download(start_date)
        print('collect over')

    def get_download(self, start_date):
        query = '''{
    "_source": ["user_login", "created_at", "properties.softwareArchitecture", "properties.softwareName", "properties.softwareOs"],
    "size": 1000,
    "query": {
        "bool": {
            "must": [
                {
                    "term": {
                        "event.keyword": "download"
                    }
                },
                {
                    "range": {
                        "created_at": {
                            "gte": "%s"
                        }
                    }
                }
            ]
        }
    }
}''' % start_date
        self.esClient.scrollSearch(self.query_index_name, search=query, func=self.get_download_func)

    def get_download_func(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            if source.get('properties'):
                action = {
                    "user_login": source.get('user_login'),
                    "created_at": source.get('created_at'),
                    "softwareArchitecture": source.get('properties').get('softwareArchitecture'),
                    "softwareName": source.get('properties').get('softwareName'),
                    "softwareOs": source.get('properties').get('softwareOs')
                }
                if source.get('user_login') in self.user_info:
                    action.update(self.user_info.get(source.get('user_login')))
                index_data = {"index": {"_index": self.index_name, "_id": hit['_id']}}
                actions += json.dumps(index_data) + '\n'
                actions += json.dumps(action) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_user_info(self):
        user_info = {}
        query = f"SELECT username, create_at, company, email, phone, photo FROM {self.table}"
        rows = self.my_client.query_data(query)
        for row in rows:
            try:
                signed_at = row[1].strftime('%Y-%m-%dT%H:%M:%S+08:00')
                item = {'signed_at': signed_at, 'company': row[2], 'email': row[3], 'phone': row[4], 'photo': row[5]}
                user_info[row[0]] = item
            except IndexError as e:
                print(f'{row[0]} user info error:', e)
        return user_info
