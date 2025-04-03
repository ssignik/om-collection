#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2023 The community Authors.
# A-Tune is licensed under the Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#     http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
# PURPOSE.
# See the Mulan PSL v2 for more details.
# Create: 2023/8/26
import json

import requests

from data.common import ESClient
from data.common_client.release_repo import ReleaseRepo


class GiteePrVersion(object):

    def __init__(self, config=None):
        self.config = config
        self.orgs = config.get('orgs')
        self.url = config.get('es_url')
        self.authorization = config.get('authorization')
        self.index_name = config.get('index_name')
        self.index_name_gitee = config.get('index_name_gitee')
        self.esClient = ESClient(config)
        self.obs_meta_org = config.get('obs_meta_org')
        self.obs_meta_repo = config.get('obs_meta_repo')
        self.obs_meta_dir = config.get('obs_meta_dir')
        self.obs_versions = config.get('obs_versions')
        self.code_base_path = config.get('code_base_path')
        self.gitee_base = config.get('gitee_base')
        self.platform = config.get('platform')

    @staticmethod
    def convert_vers(versions):
        version_query = '''('''
        for ver in versions:
            version_query += '\\"' + ver + '\\",'
        version_query += ''')'''
        return version_query

    def run(self, from_time):
        release_client = ReleaseRepo(self.config)
        repo_versions = release_client.get_repo_versions()
        for org in self.orgs.split(','):
            print('start org: ', org)
            self.reindex_pr(org, repo_versions)
            self.refresh_robot_pr(org, repo_versions)

    def reindex_pr(self, org, repo_versions):
        for repo, versions in repo_versions.items():
            if org == 'openeuler' and repo != 'kernel':
                continue
            gitee_repo = f'{self.gitee_base}/{org}/{repo}'
            version_str = self.convert_vers(versions)
            reindex_json = '''{
                "source": {
                    "index": "%s",
                    "query": {
                        "bool": {
                            "filter": [
                                {
                                    "query_string": {
                                        "analyze_wildcard": true,
                                        "query": "is_gitee_pull_request:1 AND org_name.keyword:%s AND gitee_repo.keyword:\\"%s\\" AND base_label.keyword:%s AND !tag_user_company.keyword:robot"
                                    }
                                }
                            ]
                        }
                    }
                },
                "dest": {
                    "index": "%s"
                }
            }''' % (self.index_name_gitee, org, gitee_repo, version_str, self.index_name)
            data_num = self.esClient.reindex(reindex_json.encode('utf-8'))
            if data_num == 0:
                continue
            print('reindex: %s(%s) -> %d over' % (repo, versions, data_num))

    def refresh_robot_pr(self, org, repo_versions):
        for repo, versions in repo_versions.items():
            if org == 'openeuler' and repo != 'kernel':
                continue
            print('start repo: ', repo)
            gitee_repo = f'{self.gitee_base}/{org}/{repo}'
            version_str = self.convert_vers(versions)
            query = '''{
                "size": 5000,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "query_string": {
                                    "analyze_wildcard": true,
                                    "query": "is_gitee_pull_request:1 AND org_name.keyword:%s AND gitee_repo.keyword:\\"%s\\" AND base_label.keyword:%s AND tag_user_company.keyword:robot"
                                }
                            }
                        ]
                    }
                },
                "aggs": {}
            }''' % (org, gitee_repo, version_str)
            self.esClient.scrollSearch(self.index_name_gitee, search=query, func=self.get_pr_func)

    def get_pr_func(self, hits):
        actions = ''
        for hit in hits:
            pr_details = hit.get('_source')
            body = pr_details.get('body')
            if body and 'Origin pull request:' in body:
                try:
                    prs = body.split('Origin pull request:')
                    origin_pr = prs[1].split('#')[0].strip()
                    origin_pr = origin_pr.replace('e.gitee.com/open_euler/repos', 'gitee.com')
                    user = self.get_origin_pr_author(origin_pr)
                    if user:
                        pr_details.update(user)
                except Exception as e:
                    print('error: ', e)

            index_data = {"index": {"_index": self.index_name, "_id": pr_details['id']}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(pr_details) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_origin_pr_author(self, pull_url):
        query = '''{
            "size": 10,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "pull_url.keyword:\\"%s\\" AND is_gitee_pull_request:1"
                            }
                        }
                    ]
                }
            },
            "aggs": {}
        }''' % pull_url
        url = self.url + '/' + self.index_name_gitee + '/_search'
        res = requests.post(url, headers=self.esClient.default_headers, verify=False, data=query.encode('utf-8'))
        if res.status_code != 200:
            return
        data = res.json()['hits']['hits']
        user_info = None
        for d in data:
            user_info = {
                'user_login': d['_source']['user_login'],
                'user_id': d['_source']['user_id'],
                'user_name': d['_source']['user_name'],
                'tag_user_company': d['_source']['tag_user_company'],
                'is_project_internal_user': d['_source']['is_project_internal_user'],
                'is_admin_added': 1
            }
        return user_info
