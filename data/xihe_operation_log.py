#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2025 The community Authors.
# A-Tune is licensed under the Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#     http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
# PURPOSE.
# See the Mulan PSL v2 for more details.
# Create: 2025
#
import json
import requests
from urllib3.util.retry import Retry
from data.common import ESClient
from datetime import datetime, timedelta, timezone


class XiheOperationLog(object):
    def __init__(self, config=None):
        self.config = config
        self.index_name = config.get("index_name")
        self.api_url = config.get("api_url")
        self.operate_types = config.get("operate_types")
        self.start_time = config.get("start_time")
        self.end_time = config.get("end_time", datetime.now().strftime("%Y-%m-%d"))
        self.before_days = config.get("before_days")

        self.esClient = ESClient(config)
        self.session = requests.Session()
        self.headers = {"Content-Type": "application/json"}
        self.params = {"start_time": "", "end_time": ""}

    def run(self, start=None):

        self.format_datetime()

        operate_types = self.operate_types.split(",")
        print(f"start_time: {self.start_time}")
        print(f"end_time: {self.end_time}")
        for operate_type in operate_types:
            print("start to get operation log of type: %s" % operate_type)
            users = self.get_operation_users(operate_type)
            actions = self.get_actions(users, operate_type)
            self.esClient.safe_put_bulk(actions)

    def format_datetime(self):
        if self.before_days:
            self.end_time = datetime.now()
            self.start_time = self.end_time - timedelta(int(self.before_days))
        else:
            self.start_time = datetime.strptime(self.start_time, "%Y-%m-%d")
            self.end_time = datetime.strptime(self.end_time, "%Y-%m-%d")

        tz = timezone(timedelta(hours=8))
        self.start_time = self.start_time.replace(tzinfo=tz)
        self.end_time = self.end_time.replace(tzinfo=tz)

        self.start_time = self.start_time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.end_time = self.end_time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.start_time = self.start_time[:-2] + ":" + self.start_time[-2:]
        self.end_time = self.end_time[:-2] + ":" + self.end_time[-2:]

        self.params["start_time"] = self.start_time
        self.params["end_time"] = self.end_time

    def get_operation_users(self, operate_type):
        api_url = self.api_url + operate_type
        try:
            response = requests.get(
                url=api_url,
                params=self.params,
                headers=self.headers,
                timeout=180,
                verify=False,
            )
        except Exception as e:
            print(f"get api:{api_url} failed, error: {e}")
            return []
        if response.status_code == 200:
            res = response.json().get("data")
            users = res.get("users")
            if users:
                return users
            else:
                return []
        else:
            print(response.status_code)
            print(f"Get api:{api_url} failed")
            return []

    def get_actions(self, users, operate_type):
        actions = ""

        try:
            for user in users:

                created_at = user.get("created_at")
                created_at = datetime.fromtimestamp(
                    created_at, tz=timezone(timedelta(hours=8))
                )
                created_at = created_at.strftime("%Y-%m-%dT%H:%M:%S%z")
                created_at = created_at[:-2] + ":" + created_at[-2:]

                index_data = {
                    "index": {
                        "_index": self.index_name,
                        "_id": user.get("user")
                        + "+"
                        + operate_type
                        + "+"
                        + str(created_at),
                    }
                }
                action = {
                    "user_login": user.get("user"),
                    "operate_type": operate_type,
                    "created_at": created_at,
                }

                actions += json.dumps(index_data) + "\n"
                actions += json.dumps(action) + "\n"

        except Exception as e:
            print(e)

        return actions
