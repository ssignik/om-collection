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
import time

from collections import defaultdict
from data.common import ESClient


class GitcodeUserInfo(object):
    def __init__(self, config=None):
        self.config = config
        self.esClient = ESClient(config)
        self.index_name = config.get("index_name")
        self.token = config.get("token")

        orgs_users_url = config.get("orgs_users_url")
        user_detail_url = config.get("user_detail_url")
        repo_user_url = config.get("repo_user_url")
        sig_info_url = config.get("sig_info_url")

        self.gitcode_helper = GitCodeHelper(
            self.token, orgs_users_url, user_detail_url, repo_user_url
        )
        self.dsapi_helper = DsapiHelper(sig_info_url)

    def run(self, from_time):
        # 获取所有组织的gitcode_id和user_id的对应关系
        print("get gitcode user info start")
        users = self.gitcode_helper.get_orgs_user()
        user_info = self.gitcode_helper.get_user_by_gitcode_ids(users)
        sig_infos = self.dsapi_helper.get_sig_info()
        for sig_info in sig_infos:
            self._process_sig_info(sig_info, user_info)
        self._write_json(sig_infos)

    def _process_sig_info(self, sig_info, user_info):
        self._update_user_info(sig_info, "maintainer_info", user_info)
        self._update_user_info(sig_info, "committer_info", user_info)
        self._update_repo_developer(sig_info, user_info)

    def _update_user_info(self, sig_info, info_key, user_info):
        if sig_info.get(info_key):
            for index, info in enumerate(sig_info[info_key]):
                user_id = self._get_user_id(info, user_info)
                sig_info[info_key][index]["user_id"] = user_id

    def _get_user_id(self, info, user_info):
        if info["gitcode_id"] in user_info.keys():
            return user_info[info["gitcode_id"]]
        else:
            try:
                user_id = self.gitcode_helper.get_user_by_gitcode_id(info["gitcode_id"])
            except Exception as e:
                print(e)
                user_id = None
            user_info[info["gitcode_id"]] = user_id
            return user_id

    def _update_repo_developer(self, sig_info, user_info):
        sig_info["repo_developer"] = defaultdict(dict)
        for repo in sig_info["repos"]:
            repo_name = repo.split(r"/")[-1]
            gitcode_ids = self.gitcode_helper.get_user_by_repo(repo_name)
            developers = list(
                set(gitcode_ids)
                - set(sig_info["maintainers"])
                - set(sig_info["committers"])
            )
            sig_info["repo_developer"][repo_name] = [
                {
                    "gitcode_id": developer,
                    "user_id": user_info[developer],
                    "name": "",
                    "avatar_url": "",
                }
                for developer in developers
                if user_info.get(developer) is not None
            ]
            need_add = list(set(developers) - set(user_info.keys()))
            for user in need_add:
                try:
                    user_id = self.gitcode_helper.get_user_by_gitcode_id(user)
                except Exception as e:
                    print(f"get user_id failed, user:{user}")
                    continue
                sig_info["repo_developer"][repo_name].append(
                    {
                        "gitcode_id": user,
                        "user_id": user_id,
                        "name": "",
                        "avatar_url": "",
                    }
                )
                user_info[user] = user_id

    def _write_json(self, sig_infos):
        actions = ""
        count = 0

        for sig_info in sig_infos:
            index_data = {
                "index": {
                    "_index": self.index_name,
                    "_id": sig_info.get("mailing_list"),
                }
            }
            actions += json.dumps(index_data) + "\n"
            actions += json.dumps(sig_info) + "\n"

            count += 1
            if count >= 1000:
                self.esClient.safe_put_bulk(actions)
                actions = ""
                count = 0

        if count > 0:
            self.esClient.safe_put_bulk(actions)


class RequestHandler:
    def __init__(self, timeout=None):
        self.timeout = timeout if not timeout else 60
        self._session = requests.Session()

    def get(self, url, is_json=True):
        print(f"requsetHandler get url:{url}")
        resp = self._session.get(url, timeout=(self.timeout, self.timeout))
        if not str(resp.status_code).startswith("20"):
            raise RuntimeError(
                "get the url failed, return status is:{} the detail is:{}".format(
                    resp.status_code, resp.content
                )
            )
        if is_json:
            return resp.json()
        return resp.content

    def post(self, url, json_data=None, data=None, is_suppress_error=False):
        print(f"requsetHandler post url:{url}")
        resp = self._session.post(
            url, json=json_data, data=data, timeout=(self.timeout, self.timeout)
        )
        if not str(resp.status_code).startswith("20") and not is_suppress_error:
            raise RuntimeError(
                "post the url failed, return status is:{} the detail is:{}".format(
                    resp.status_code, resp.content
                )
            )
        return resp.status_code, resp.json()

    def delete(self, url):
        print(f"requsetHandler delete url:{url}")
        resp = self._session.delete(url, timeout=(self.timeout, self.timeout))
        if not str(resp.status_code).startswith("20"):
            raise RuntimeError(
                "delete the url failed, return status is:{} the detail is:{}".format(
                    resp.status_code, resp.content
                )
            )
        return resp.status_code


class DsapiHelper:

    def __init__(self, sig_info_url, request_handler=None):
        self.sig_info_url = sig_info_url
        if request_handler is None:
            self._request_handler = RequestHandler()
        else:
            self._request_handler = request_handler

    def get_sig_info(self):
        print("get sig info")
        resp = self._request_handler.get(self.sig_info_url)
        return resp["data"]


class GitCodeHelper:

    def __init__(
        self,
        token,
        orgs_users_url,
        user_detail_url,
        repo_user_url,
        request_handler=None,
    ):
        self._token = token

        self.orgs_users_url = orgs_users_url
        self.user_detail_url = user_detail_url
        self.repo_user_url = repo_user_url

        if request_handler is None:
            self._request_handler = RequestHandler()
        else:
            self._request_handler = request_handler

    def get_orgs_user(self):
        print("get orgs user")
        users = list()
        page = 1
        while True:
            url = self.orgs_users_url.format(self._token, page)
            resp = self._request_handler.get(url)
            users.extend([user["login"] for user in resp])
            if len(resp) >= 100:
                page += 1
                continue
            break
        return users

    def get_user_by_gitcode_ids(self, users):
        print("get user by gitcode ids")
        user_infos = dict()
        for user in users:
            url = self.user_detail_url.format(user, self._token)
            try:
                resp = self._request_handler.get(url)
                user_infos[user] = resp["user"]["id"]
            except Exception as e:
                print(f"get user by gitcode ids failed, user:{user}, error:{e}")
                user_infos[user] = None
            time.sleep(1)  # to resolve 429
        return user_infos

    def get_user_by_gitcode_id(self, user):
        print("get user by gitcode id")
        url = self.user_detail_url.format(user, self._token)
        resp = self._request_handler.get(url)
        return resp["user"]["id"]

    def get_user_by_repo(self, repo_name):
        print("get user by repo")
        users = list()
        page = 1
        while True:
            url = self.repo_user_url.format(repo_name, self._token, page)
            try:
                resp = self._request_handler.get(url)
            except Exception as e:
                print(f"get user by repo failed, repo:{repo_name}, error:{e}")
                break
            time.sleep(1)  # to resolve 429
            users.extend([user["username"] for user in resp])
            if len(resp) >= 100:
                page += 1
                continue
            break
        return users
