#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2022 The community Authors.
# A-Tune is licensed under the Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#     http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
# PURPOSE.
# See the Mulan PSL v2 for more details.
# Create: 2022
#
import json
import requests
from data.common import ESClient

retry_times = 3


class XiheDown(object):
    def __init__(self, config=None):
        self.config = config
        self.index_name = config.get('index_name')
        self.count_type = config.get('count_type')
        self.type = config.get('type')
        self.model_name = config.get('model_name')
        self.api_url = config.get('api_url')
        self.is_collect_big_model = config.get('is_collect_big_model')
        self.is_collect_register_count = config.get('is_collect_register_count')

        self.esClient = ESClient(config)
        self.session = requests.Session()
        self.headers = {'Content-Type': 'application/json', 'XIHE-TOKEN': config.get('xihe-token')}
        self.retry_cnt = 0

    def run(self, start=None):
        if self.is_collect_big_model == 'true':
            self.get_big_model()
        if self.is_collect_register_count == 'true':
            self.get_register_count()

    def get_big_model(self):
        actions = ''
        if self.count_type:
            for count_type in self.count_type.split(','):
                actions += self.get_download(self.api_url, count_type)
        if self.type:
            for t in self.type.split(','):
                base_url = self.api_url + 'd1/'
                actions += self.get_download(base_url, t)
        if self.model_name:
            for name in self.model_name.split(','):
                base_url = self.api_url + 'd1/bigmodel/'
                actions += self.get_download(base_url, name)
        self.esClient.safe_put_bulk(actions)

    def get_download(self, base_url, count_type):
        url = base_url + count_type
        actions = ''
        # response = requests.get(url=url, headers=self.headers, verify=False)
        response = self.get_api(url)
        try:
            if response.status_code == 200:
                res = response.json().get('data')
                update_time = res.get('update_at')
                action = {
                    'update_time': update_time,
                    count_type: res.get('counts'),
                    'is_project_internal_user': 0
                }
                if count_type in self.model_name:
                    action.update({'model': count_type})
                    action.update({'counts': res.get('counts')})

                index_data = {"index": {"_index": self.index_name, "_id": count_type + update_time}}
                actions += json.dumps(index_data) + '\n'
                actions += json.dumps(action) + '\n'
        except AttributeError as e:
            print('Get api: ' + url + ' error')
        return actions

    def get_api(self, url):
        try:
            response = requests.get(url=url, headers=self.headers, verify=False, timeout=60)
            if response.status_code != 200 and self.retry_cnt < retry_times:
                self.retry_cnt += 1
                print({'url': url, 'code': response.status_code, 'retry': self.retry_cnt})
                response = self.get_api(url)
        except requests.exceptions.RequestException as e:
            while self.retry_cnt < retry_times:
                try:
                    self.retry_cnt += 1
                    print('Retry ' + str(self.retry_cnt) + ' times: ' + url)
                    return self.get_api(url)
                finally:
                    pass
        except Exception as e:
            raise e
        else:
            self.retry_cnt = 0
            return response

    def get_register_count(self):
        actions = ''
        response = self.get_api(self.api_url)
        try:
            if response.status_code != 200:
                return
            res = response.json().get('data')
            update_time = res.get('update_at')
            total = res.get('total')
            data = res.get('data')
            for item in data:
                action = item
                action.update({
                    'total': total,
                    'update_time': update_time
                })
                doc_id = item.get('name') + update_time.split('T')[0]
                index_data = {"index": {"_index": self.index_name, "_id": doc_id}}
                actions += json.dumps(index_data) + '\n'
                actions += json.dumps(action) + '\n'
        except AttributeError as e:
            print('Get api: ' + self.api_url + ' error')
        self.esClient.safe_put_bulk(actions)
