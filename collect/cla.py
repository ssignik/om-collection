#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 The community Authors.
# A-Tune is licensed under the Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#     http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
# PURPOSE.
# See the Mulan PSL v2 for more details.
# Create: 2020-05
#

import json

import requests

AUTH = 'auth'


class ClaClient(object):

    def __init__(self, config):
        self.api_url = config.get('cla_api_url', 'https://clasign.osinfra.cn/api/v1')
        self.platform = config.get('platform')
        self.username = config.get('cla_username')
        self.password = config.get('cla_password')
        self.timeout = config.get('timeout', 60)
        self.gitee_token = config.get('gitee_token')

    def get_token_cla(self):
        data = json.dumps({'token': self.gitee_token})
        auth_url = f'{self.api_url}/{AUTH}/{self.platform}'
        token_info = self.fetch_cla(method='post', url=auth_url, data=data)
        token = token_info['data']['access_token']
        return token

    def fetch_cla(self, method='get', url=None, headers=None, data=None, params=None):
        req = requests.request(method, url=url, data=data, headers=headers, params=params, timeout=self.timeout)
        if req.status_code != 200:
            print("cla api error: ", req.text)
        res = json.loads(req.text)
        return res
