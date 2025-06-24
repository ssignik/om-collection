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
# Create: 2022-03
#
import hashlib
import json
from datetime import datetime

import xlrd
from collect.pg_sql import PgSqlClient

from data.common import ESClient


class BlueZoneUser(object):
    def __init__(self, config=None):
        self.config = config
        self.org = config.get('org')
        self.esClient = ESClient(config)
        self.user_index = config.get('user_index')
        self.gitee_pr_issue_index = config.get('gitee_pr_issue_indexs')
        self.gitee_commit_index = config.get('gitee_commit_indexs')
        self.github_pr_issue_index = config.get('github_pr_issue_indexs')
        self.github_commit_index = config.get('github_commit_indexs')
        self.gitcode_pr_issue_index = config.get('gitcode_pr_issue_indexs')
        self.gitcode_commit_index = config.get('gitcode_commit_indexs')
        self.target_index = config.get('target_index')
        self.users = []
        self.user = {}
        self.startTime = config.get('start_time')
        self.endTime = config.get('end_time')
        self.base_url = config.get('base_url')

    def run(self, from_date):
        print('Start collection BlueZoneUserContributes')
        current_date = datetime.today().strftime('%Y-%m-%d')
        self.startTime = self.startTime if self.startTime else current_date
        self.endTime = self.endTime if self.endTime else current_date

        self.users = []
        self.get_blue_users()
        for user in self.users:
            print('******* %s *******' % user['name'])
            self.user = user
            user.pop('product_line_code', None)
            emails = ';'.join(user['emails'])
            user['emails'] = emails
            self.user.pop('created_at', None)
            if user['gitee_id'] is not None and user['gitee_id'] != '':
                self.get_pr_gitee()
                self.get_issue_gitee()
                self.get_pr_issue_comment_gitee()
            if user['github_id'] is not None and user['github_id'] != '':
                self.get_pr_github()
                self.get_issue_github()
                self.get_pr_issue_comment_github()
            if user.get('gitcode_id'):
                self.get_pr_issue_comment_gitcode()
            self.get_commit(indexs_str=self.github_commit_index)
            self.get_commit(indexs_str=self.gitee_commit_index)
            self.get_commit(indexs_str=self.gitcode_commit_index)

    def userFromExcel(self):
        wb = xlrd.open_workbook("C:\\Users\\Administrator\\Desktop\\blue_zone_user.xls")
        sh = wb.sheet_by_name("Sheet2")

        cell_name_index_dict = {}
        for i in range(sh.ncols):
            cell_name = sh.cell_value(0, i)
            cell_name_index_dict.update({cell_name: i})

        actions = ''
        for r in range(1, sh.nrows):
            name = self.getCellValue(r, '姓名', sh, cell_name_index_dict)
            org = self.getCellValue(r, '项目群', sh, cell_name_index_dict)
            gitee_id = self.getCellValue(
                r, 'gitee_id', sh, cell_name_index_dict)
            github_id = self.getCellValue(
                r, 'github_id', sh, cell_name_index_dict)
            emails = self.getCellValue(r, '邮箱', sh, cell_name_index_dict)

            if gitee_id is not None and gitee_id != '':
                id = gitee_id
            else:
                id = github_id

            action = {'name': name,
                      'org': org,
                      'github_id': github_id,
                      'gitee_id': gitee_id,
                      'emails': emails,
                      'created_at': '2021-08-11T11:21:39+08:00'}

            index_data = {
                "index": {"_index": "blue_zone_users_test", "_id": id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(action) + '\n'

        self.esClient.safe_put_bulk(actions)

    def getCellValue(self, row_index, cell_name, sheet, cell_name_index_dict):
        if cell_name not in cell_name_index_dict:
            return ''
        cell_value = sheet.cell_value(
            row_index, cell_name_index_dict.get(cell_name))
        return cell_value

    def get_blue_users(self):
        users_search = '''{"size": 10000,"query": {"bool": {"must": [{"match_all": {}}]}}}'''
        self.esClient.scrollSearch(
            index_name=self.user_index, search=users_search, func=self.blue_users_func)

    def blue_users_func(self, hits):
        for hit in hits:
            self.users.append(hit['_source'])

    def get_pr_gitee(self):
        indexs = str(self.gitee_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "base_label_ref",
                          "head_label_ref",
                          "body",
                          "issue_title",
                          "pull_state",
                          "gitee_repo",
                          "pull_id",
                          "url",
                          "is_gitee_pull_request"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_gitee_pull_request": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['gitee_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.pr_func_gitee)

    def pr_func_gitee(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'target_branch': '' if source.get('base_label_ref') is None else source['base_label_ref'],
                'source_branch': '' if source.get('head_label_ref') is None else source['head_label_ref'],
                'pr_title': source['issue_title'],
                'pr_state': source['pull_state'],
                'repo': source['gitee_repo'],
                'is_pr': source['is_gitee_pull_request'],
                'pull_id': source['pull_id'],
                'pr_body': '' if source.get('body') is None else source['body'],
                'url': source['url'],
            }
            repo_data.update(self.user)
            id = str(source['gitee_repo']) + 'pr' + str(source['pull_id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_issue_gitee(self):
        indexs = str(self.gitee_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "closed_at",
                          "priority",
                          "issue_title",
                          "body",
                          "issue_state",
                          "gitee_repo",
                          "issue_id",
                          "url",
                          "is_gitee_issue"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_gitee_issue": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['gitee_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.issue_func_gitee)

    def issue_func_gitee(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            body = source['body'] if 'body' in source else ''
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'closed_at': source['closed_at'],
                'priority': 0 if source.get('priority') is None else source['priority'],
                'issue_title': source['issue_title'],
                'issue_state': source['issue_state'],
                'repo': source['gitee_repo'],
                'is_issue': source['is_gitee_issue'],
                'issue_id': source['issue_id'],
                'issue_body': body,
                'url': source['url'],
            }
            repo_data.update(self.user)
            id = str(source['gitee_repo']) + 'issue' + str(source['issue_id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_pr_issue_comment_gitee(self):
        indexs = str(self.gitee_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "issue_id",
                          "pull_id",
                          "issue_id_in_repo",
                          "pull_id_in_repo",
                          "id",
                          "gitee_repo",
                          "url",
                          "issue_url",
                          "pull_url",
                          "body",
                          "is_gitee_comment"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_gitee_comment": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['gitee_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.pr_issue_comment_func_gitee)

    def pr_issue_comment_func_gitee(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            if 'url' not in source:
                url = ''
                if 'issue_url' in source:
                    url = source['issue_url']
                if 'pull_url' in source:
                    url = source['pull_url']
            else:
                url = source['url']
            parent = ''
            parent_id = ''
            if 'issue_id' in source:
                parent = 'issue_comment'
                parent_id = source['issue_id_in_repo']
            if 'pull_id' in source:
                parent = 'pr_comment'
                parent_id = source['pull_id_in_repo']
            body = source['body'] if 'body' in source else ''
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'id': source['id'],
                'repo': source['gitee_repo'],
                'is_comment': source['is_gitee_comment'],
                'comment_body': body,
                'parent_id': parent_id,
                'url': url,
            }
            repo_data.update(self.user)
            id = str(source['gitee_repo']) + parent + str(source['id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_commit(self, indexs_str):
        indexs = str(indexs_str).split(";")
        emails_str = self.user['emails']
        emails = emails_str.split(";")
        for email in emails:
            search = '''{
                          "size": 1000,
                          "_source": {
                            "includes": [
                              "created_at",
                              "add",
                              "remove",
                              "file_changed",
                              "repo",
                              "commit_id",
                              "email"
                            ]
                          },
                          "query": {
                            "bool": {
                              "must": [
                                {
                                  "match": {
                                    "email.keyword": "%s"
                                  }
                                },
                                {
                                  "term": {
                                    "is_merge": 0
                                  }
                                },
                                {
                                  "range": {
                                    "created_at": {
                                      "gte": "%s",
                                      "lte": "%s"
                                    }
                                  }
                                }
                              ]
                            }
                          }
                        }''' % (email.strip(), self.startTime, self.endTime)
            for index in indexs:
                self.esClient.scrollSearch(
                    index_name=index, search=search, scroll_duration='2m', func=self.commit_func)
        self.user['emails'] = emails_str

    def commit_func(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            self.user['emails'] = source['email']
            repo_data = {
                'created_at': source['created_at'],
                'commit_id': source['commit_id'],
                'repo': source['repo'],
                'line_add': source['add'],
                'line_remove': source['remove'],
                'file_changed': source['file_changed'],
                'is_commit': 1,
            }
            repo_data.update(self.user)
            id = str(source['repo']) + 'commit' + str(source['commit_id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_pr_github(self):
        indexs = str(self.github_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "base_label_ref",
                          "head_label_ref",
                          "pr_body",
                          "pr_title",
                          "pr_state",
                          "github_repo",
                          "pr_id",
                          "html_url",
                          "is_github_pr"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_github_pr": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['github_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.pr_func_github)

    def pr_func_github(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'target_branch': '' if source.get('base_label_ref') is None else source['base_label_ref'],
                'source_branch': '' if source.get('head_label_ref') is None else source['head_label_ref'],
                'pr_title': source['pr_title'],
                'pr_state': source['pr_state'],
                'repo': 'https://github.com/' + source['github_repo'],
                'is_pr': source['is_github_pr'],
                'pull_id': source['pr_id'],
                'pr_body': source['pr_body'],
                'url': source['html_url'],
            }
            repo_data.update(self.user)
            id = str(source['github_repo']) + 'pr' + str(source['pr_id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_issue_github(self):
        indexs = str(self.github_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "closed_at",
                          "issue_title",
                          "issue_state",
                          "issue_body",
                          "github_repo",
                          "issue_id",
                          "html_url",
                          "is_github_issue"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_github_issue": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['github_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.issue_func_github)

    def issue_func_github(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'closed_at': source['closed_at'],
                'priority': 0,
                'issue_title': source['issue_title'],
                'issue_state': source['issue_state'],
                'repo': 'https://github.com/' + source['github_repo'],
                'is_issue': source['is_github_issue'],
                'issue_id': source['issue_id'],
                'issue_body': source['issue_body'],
                'url': source['html_url'],
            }
            repo_data.update(self.user)
            id = str(source['github_repo']) + 'issue' + str(source['issue_id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_pr_issue_comment_github(self):
        indexs = str(self.github_pr_issue_index).split(";")
        search = '''{
                      "size": 1000,
                      "_source": {
                        "includes": [
                          "created_at",
                          "updated_at",
                          "issue_id",
                          "pr_id",
                          "issue_number",
                          "pr_number",
                          "id",
                          "github_repo",
                          "html_url",
                          "pr_comment_body",
                          "issue_comment_body",
                          "is_github_comment"
                        ]
                      },
                      "query": {
                        "bool": {
                          "must": [
                            {
                              "match": {
                                "user_login.keyword": "%s"
                              }
                            },
                            {
                              "term": {
                                "is_github_comment": "1"
                              }
                            },
                            {
                              "range": {
                                "updated_at": {
                                  "gte": "%s",
                                  "lte": "%s"
                                }
                              }
                            }
                          ]
                        }
                      }
                    }''' % (self.user['github_id'].strip(), self.startTime, self.endTime)
        for index in indexs:
            self.esClient.scrollSearch(
                index_name=index, search=search, scroll_duration='2m', func=self.pr_issue_comment_func_github)

    def pr_issue_comment_func_github(self, hits):
        actions = ''
        for hit in hits:
            source = hit['_source']
            parent = ''
            body = ''
            parent_id = ''
            if 'issue_id' in source:
                parent = 'issue_comment'
                body = source['issue_comment_body']
                parent_id = source['issue_number']
            if 'pr_id' in source and 'pr_comment_body' in source:
                parent = 'pr_comment'
                body = source['pr_comment_body']
                parent_id = source['pr_number']
            repo_data = {
                'created_at': source['created_at'],
                'updated_at': source['updated_at'],
                'id': source['id'],
                'repo': 'https://github.com/' + source['github_repo'],
                'is_comment': source['is_github_comment'],
                'comment_body': body,
                'parent_id': parent_id,
                'url': source['html_url'],
            }
            repo_data.update(self.user)
            id = str(source['github_repo']) + parent + str(source['id'])
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)

    def get_pr_issue_comment_gitcode(self):
        indexs = str(self.gitcode_pr_issue_index).split(";")
        pg = PgSqlClient(self.config)
        gitcode_id = self.user['gitcode_id'].strip()
        for index in indexs:
            cursor_query = f"""
                SELECT uuid,body,created_at,updated_at,tag_url,comment_type,repo_path,namespace,html_url
                FROM {index}
                WHERE is_comment = 1 AND user_login = '{gitcode_id}' AND updated_at >= '{self.startTime}' AND updated_at <= '{self.endTime}' AND uuid > %s
                ORDER BY uuid
                LIMIT %s;
            """
            query = f"""
                SELECT uuid,body,created_at,updated_at,tag_url,comment_type,repo_path,namespace,html_url
                FROM {index}
                WHERE is_comment = 1 AND user_login = '{gitcode_id}' AND updated_at >= '{self.startTime}' AND updated_at <= '{self.endTime}'
                ORDER BY uuid
                LIMIT %s;
            """
            pg.fetch_all(self.pr_issue_comment_func_gitcode,
                         cursor_query, query)

    def pr_issue_comment_func_gitcode(self, rows):
        actions = ''
        for row in rows:
            body = row[1]
            parent_id = row[4].split('/')[-1]
            created_at = row[2].strftime(
                '%Y-%m-%dT%H:%M:%S') + row[2].strftime('%z')[:3] + ':' + row[2].strftime('%z')[3:]
            updated_at = row[3].strftime(
                '%Y-%m-%dT%H:%M:%S') + row[3].strftime('%z')[:3] + ':' + row[3].strftime('%z')[3:]
            repo_data = {
                'created_at': created_at,
                'updated_at': updated_at,
                'repo': self.base_url % ('gitcode', row[7], row[6]),
                'is_comment': 1,
                'comment_body': body,
                'parent_id': parent_id,
                'url': row[8]
            }
            repo_data.update(self.user)
            id = repo_data['repo'] + row[0]
            index_id = hashlib.md5(id.encode('utf-8')).hexdigest()
            index_data = {
                "index": {"_index": self.target_index, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(repo_data) + '\n'
        self.esClient.safe_put_bulk(actions)
