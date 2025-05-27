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
import re
import subprocess
import threading
import time
import traceback
import types
from collections import defaultdict
from datetime import datetime, timedelta
from json import JSONDecodeError
from logging import Logger as logger
from urllib.parse import quote

import dateutil.parser
import dateutil.rrule
import dateutil.tz
import urllib3
from dateutil.relativedelta import relativedelta

from collect.gitee import GiteeClient
from dateutil import parser
from tzlocal import get_localzone

urllib3.disable_warnings()
import os

import pytz
import requests
import yaml

from geopy.geocoders import Nominatim
from configparser import ConfigParser


# Default sleep time and retries to deal with connection/server problems
DEFAULT_SLEEP_TIME = 1
MAX_RETRIES = 5
globa_threadinfo = threading.local()
config = ConfigParser()
IP_API_URL = 'https://dsapi.osinfra.cn/query/ip/location'

try:
    config.read('config.ini', encoding='UTF-8')
    retry_time = config.getint('general', 'retry_time', )
    retry_sleep_time = config.getint('general', 'retry_sleep_time')
except BaseException as ex:
    retry_sleep_time = 10
    retry_time = 10


def globalExceptionHandler(func):
    def warp(*args, **kwargs):
        try:
            # 第一次进来初始化重试次数变量
            if args[len(args) - 1] != "retry":
                globa_threadinfo.num = 0
                # 重试是否成功0 未成功，1 成功
                globa_threadinfo.retrystate = 0
            newarg = []
            # 执行func 参数去除retry标识
            for i in args:
                if i != 'retry':
                    newarg.append(i)
            response = func(*newarg, **kwargs)
        except requests.exceptions.RequestException as ex:
            while globa_threadinfo.num < retry_time and globa_threadinfo.retrystate == 0:
                try:
                    globa_threadinfo.num += 1
                    print(
                        "retry:" + threading.currentThread().getName() + str(func.__name__) + ":" + str(
                            globa_threadinfo.num) + "次")
                    print("error:" + str(ex))
                    print(args)
                    time.sleep(retry_sleep_time)
                    # 防止重复添加标识
                    if 'retry' not in args:
                        response = warp(*args, "retry", **kwargs)
                    else:
                        response = warp(*args, **kwargs)
                    return response
                finally:
                    pass
        except Exception as e:
            print("globalExceptionHandler Exception: fetch error :" + str(
                e) + "retry:" + threading.currentThread().getName() + str(func.__name__) + ":" + str(
                globa_threadinfo.num) + " Count")
            raise e
        else:
            print(
                "globalExceptionHandler else: check response instance." + "retry:" + threading.currentThread().getName() + str(
                    func.__name__) + ":" + str(
                    globa_threadinfo.num) + "次")
            if isinstance(response, requests.models.Response):
                if response.status_code == 401 or response.status_code == 403:
                    print({"状态码": response.status_code})
                else:
                    print("globalExceptionHandler else: response.status_code is not 401 and 403.")
            else:
                print("globalExceptionHandler else: response is not requests.models.Response.")
            # 重试成功，修改状态
            globa_threadinfo.retrystate = 1
            globa_threadinfo.num = 0
            print("globalExceptionHandler else: retry success globa_threadinfo.retrystate set to 1.")
            return response

    return warp


class ESClient(object):

    def __init__(self, config=None):
        self.url = config.get('es_url')
        self.from_date = config.get('from_date')
        self.index_name = config.get('index_name')
        self.sig_index = config.get('sig_index')
        self.query_index_name = config.get('query_index_name')
        self.authorization = config.get('authorization')
        self.default_headers = {
            'Content-Type': 'application/json'
        }
        self.internalUsers = []
        self.internalUsers = self.getItselfUsers()
        self.internal_users = config.get('internal_users', 'users')
        self.enterpriseUsers = []
        self.internal_company_name = config.get('internal_company_name', 'internal_company')
        self.is_gitee_enterprise = config.get('is_gitee_enterprise')
        self.enterpriseUsers = []
        self.gitee_token = config.get('gitee_token')
        self.is_update_tag_company = config.get('is_update_tag_company', 'true')
        self.is_update_tag_company_cla = config.get('is_update_tag_company_cla', 'false')
        self.data_yaml_url = config.get('data_yaml_url')
        self.data_yaml_path = config.get('data_yaml_path')
        self.company_yaml_url = config.get('company_yaml_url')
        self.company_yaml_path = config.get('company_yaml_path')
        self.index_name_cla = config.get('index_name_cla')
        self.index_name_org = config.get('index_name_org')
        self.giteeid_company_dict = {}
        self.giteeid_company_change_dict = defaultdict(dict)
        if self.authorization:
            self.default_headers['Authorization'] = self.authorization
        self.item = config.get("item")
        self.orgs = self.getOrgs(config.get('orgs'))
        self.company_location_index = config.get('company_location_index')
        self.email_gitee_authorization = config.get('email_gitee_authorization')
        self.feature_write_index = config.get('feature_write_index')
        self.index_name_gitee = config.get('index_name_gitee')

    def update_feature_index(self, action, index_id):
        header = {
            "Content-Type": 'application/json',
            'Authorization': self.authorization
        }
        query_json = json.dumps(action, ensure_ascii = False)
        query_url = self.url + '/' + self.feature_write_index +  '/_doc' + '/' + index_id
        res = requests.post(query_url, headers=header, verify=False, data = query_json.encode('utf-8'))
        if (res.status_code != 200):
            return

    def get_data_from_index(self, issue_url):
        '''
        从es数据库中获取issue_url对应的tag_user_company, user_login, sig_names。如果不存在则返回空字符串。
        '''
        query = '''{
            "size": 10000,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "!is_removed: 1 AND issue_url:(\\\"%s\\\") AND is_gitee_issue:1"
                            }
                        }
                    ]
                }
            },
            "_source":[
            "tag_user_company",
            "user_login",
            "sig_names"
            ]
        }''' % issue_url
        header = {
            "Content-Type": 'application/json',
            'Authorization': self.authorization,
            'Connection':'close'
        }
        url = self.url + '/' + self.index_name_gitee + '/_search'
        res = requests.post(url, headers=header, verify=False, data=query.encode('utf-8'))
        if res.status_code != 200:
            return
        data = res.json()['hits']['hits']
        res.close()
        if len(data) != 0:
            return [data[0]['_source']['user_login'], data[0]['_source']['tag_user_company'], data[0]['_source']['sig_names']]
        else:
            return ["", "", ""]

    def getObsAllPackageName(self):
        search_json = '''{
         "size": 0,
         "aggs": {
           "each_project": {
             "terms": {
               "size": 10000,
               "field": "package.keyword",
               "order": {
                 "_term": "asc"
               }
             }
           }
         }
       }'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        return res.json()

    def getObsSumAndCount(self, packagename, current_month_first_date):
        search_json = '''{
                      "size": 0,
                      "query": {
                        "bool": {
                          "filter": [
                            {
                              "range": {
                                "created_at": {
                                  "gte": "%s",
                                  "lte": "now"
                                }
                              }
                            },
                            {
                              "term": {
                                "success": "1"
                              }
                            },
                            {
                              "query_string": {
                                "analyze_wildcard": true,
                                "query": "package.keyword:%s"
                              }
                            }
                          ]
                        }
                      },
                      "aggs": {
                        "each_month": {
                          "date_histogram": {
                            "field": "created_at",
                            "interval": "month",
                            "format": "yyyy-MM-dd"
                          },
                          "aggs": {
                            "each_project": {
                              "terms": {
                                "size": 50,
                                "field": "project.keyword",
                                "order": {
                                  "_term": "asc"
                                }
                              },
                              "aggs": {
                                "each_hostarch": {
                                  "terms": {
                                    "field": "hostarch.keyword"
                                  },
                                  "aggs": {
                                    "avg_duration": {
                                      "avg": {
                                        "field": "duration"
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }''' % (current_month_first_date, packagename)
        res = self.request_get(self.getSearchUrl(index_name=self.index_name),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        return res.json()

    def getRepoSigs(self, query_es=None, query_auth=None):
        dict_comb = defaultdict(dict)
        if self.sig_index:
            search = '''{
  "size": 10000,
  "query": {
    "bool": {
      "must": [
        {
          "term": {
            "is_sig_original": "1"
          }
        },
        {
          "query_string": {
            "query": "!is_removed:1"
          }
        }
      ]
    }
  }
}'''
            url = self.getSearchUrl(index_name=self.sig_index)
            _headers = self.default_headers
            if query_es and query_auth:
                url = self.getSearchUrl(query_es, self.sig_index)
                _headers = {
                    'Content-Type': 'application/json',
                    'Authorization': query_auth
                }
            else:
                url = self.getSearchUrl(index_name=self.sig_index)
                _headers = self.default_headers
            res = self.request_get(url, data=search, headers=_headers)
            if res.status_code != 200:
                print("The index not exist")
                return dict_comb
            data = res.json()
            for d in data['hits']['hits']:
                source = d['_source']
                sig = source['sig_name']
                repos = source['repos']
                dt = defaultdict(dict)
                for repo in repos:
                    dt.update({repo: [sig]})
                combined_keys = dict_comb.keys() | dt.keys()
                dict_comb = {key: dict_comb.get(key, []) + dt.get(key, []) for key in combined_keys}
        return dict_comb

    def getRepoOrganizations(self, field, company_aliases_dict, is_sig_info_yaml=True, query_es=None, query_auth=None):
        dict_comb = defaultdict(dict)
        if self.sig_index:
            search = '''{
                          "size": 0,
                          "query": {
                            "bool": {
                              "filter": [
                                {
                                  "query_string": {
                                    "analyze_wildcard": true,
                                    "query": "owner_type.keyword:\\"maintainers\\" AND !is_removed:1"
                                  }
                                }
                              ]
                            }
                          },
                          "aggs": {
                            "repos": {
                              "terms": {
                                "field": "repo_name.keyword",
                                "size": 20000,
                                "min_doc_count": 1
                              },
                              "aggs": {
                                "orgs": {
                                  "terms": {
                                    "field": "%s.keyword",
                                    "size": 10000,
                                    "min_doc_count": 1
                                  }
                                }
                              }
                            }
                          }
                        }''' % field
            
            _headers = self.default_headers
            url = self.getSearchUrl(index_name=self.sig_index)
            if query_es and query_auth:
                url = self.getSearchUrl(query_es, self.sig_index)
                _headers = {
                    'Content-Type': 'application/json',
                    'Authorization': query_auth
                }
            res = self.request_get(url, data=search, headers=_headers)
            if res.status_code != 200:
                print("The index not exist")
                return dict_comb
            data = res.json()
            for repo in data['aggregations']['repos']['buckets']:
                repo_name = repo['key']
                buckets = repo['orgs']['buckets']
                if len(buckets) == 0:
                    continue
                org_names = []
                for bucket in buckets:
                    org_name = bucket['key']
                    if org_name == 'NA':
                        continue
                    if company_aliases_dict is not None:
                        if org_name in company_aliases_dict:
                            org_name = company_aliases_dict[org_name]
                        elif is_sig_info_yaml:
                            print('*** Not found company aliases: %s' % org_name)
                    org_names.append(org_name)
                dict_comb[repo_name] = org_names
        return dict_comb

    def getLastRepoSigs(self):
        dict_comb = defaultdict(dict)
        if self.index_name is None:
            return {}
        search = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "!is_removed:1"
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "2": {
                    "terms": {
                        "field": "gitee_repo.keyword",
                        "size": 20000
                    },
                    "aggs": {
                        "3": {
                            "terms": {
                                "field": "sig_names.keyword",
                                "size": 100
                            },
                            "aggs": {}
                        }
                    }
                }
            }
        }'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name),
                               data=search, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return dict_comb
        data = res.json()
        for d in data['aggregations']['2']['buckets']:
            repo = d['key'][18:]
            sig_names = [sig['key'] for sig in d['3']['buckets']]
            dict_comb.update({repo: sig_names})
        return dict_comb

    def getAllGiteeRepo(self):
        search_json = '''{
  "size": 0,
  "aggs": {
    "repos": {
      "terms": {
        "field": "gitee_repo.keyword",
        "size": 20000,
        "order": {
          "_key": "desc"
        },
        "min_doc_count": 0
      }
    }
  }
}'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        return res.json()

    def getOrgByEmail(self):
        if self.index_name_org is None:
            return

        email_org_dict = {}
        search_json = '''{
                          "size": 10000,
                          "_source": {
                            "includes": [
                              "email",
                              "organization"
                            ]
                          },
                          "query": {
                            "bool": {
                              "must": [
                                {
                                  "term": {
                                    "is_cla": "1"
                                  }
                                }
                              ]
                            }
                          }
                        }'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name_org),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        data = res.json()
        for hits in data['hits']['hits']:
            source_data = hits['_source']
            email_org_dict.update({source_data['email']: source_data['organization']})
        return email_org_dict

    def getOrgByGiteeID(self):
        dic = {}
        giteeid_orgs_dict = defaultdict(dict)

        if self.index_name_org is None:
            return dic, giteeid_orgs_dict

        search_json = '''{
                          "size": 10000,
                          "_source": {
                            "includes": [
                              "gitee_id",
                              "organization",
                              "created_at"
                            ]
                          },
                          "query": {
                            "bool": {
                              "must": [
                                {
                                  "term": {
                                    "is_cla": "1"
                                  }
                                }
                              ]
                            }
                          }
                        }'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name_org),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        data = res.json()
        for hits in data['hits']['hits']:
            source_data = hits['_source']
            gitee_id = source_data['gitee_id']
            if gitee_id is None:
                continue
            value = {source_data['created_at']: source_data['organization']}
            giteeid_orgs_dict[gitee_id].update(value)

        dic_change = giteeid_orgs_dict.copy()
        for key, vMap in giteeid_orgs_dict.items():
            if len(set(vMap.values())) > 1:
                last_time = max(vMap.keys())
                dic.update({key: vMap[last_time]})
            else:
                dic.update({key: list(vMap.values())[0]})
                dic_change.pop(key)

        return dic, dic_change

    def get_mark_org(self, field):
        org_dic = {}
        field_orgs_dict = defaultdict(dict)
        if self.index_name_org is None:
            return org_dic, field_orgs_dict
        search_json = '''{
            "size": 1000,
            "_source": {
                "includes": [
                    "gitee_id",
                    "github_id",
                    "company",
                    "username",
                    "created_at"
                ]
            }
        }'''

        scroll_duration = "1m"
        resp_list = []

        def func(resp):
            for item in resp:
                resp_list.append(item['_source'])

        self.scrollSearch(self.index_name_org, search_json, scroll_duration, func)

        for hit in resp_list:
            field_id = hit.get(field, None)
            if field_id is None:
                continue
            value = {hit['created_at']: hit['company']}
            field_orgs_dict[field_id].update(value)

        dic_change = field_orgs_dict.copy()
        for key, vMap in field_orgs_dict.items():
            if len(vMap) > 1:
                last_time = max(vMap.keys())
                org_dic.update({key: vMap[last_time]})
            else:
                org_dic.update({key: list(vMap.values())[0]})
                dic_change.pop(key)

        return org_dic, dic_change

    def getuserInfoFromCla(self):
        if self.is_update_tag_company_cla != 'true' or self.index_name_cla is None:
            return {}

        giteeid_company_dict = {}
        search_json = '''{
                          "size": 10000,
                          "_source": {
                            "includes": [
                              "employee_id",
                              "corporation",
                              "is_admin_added"
                            ]
                          },
                          "query": {
                            "bool": {
                              "must": [
                                {
                                  "term": {
                                    "is_corporation_signing": "1"
                                  }
                                }
                              ]
                            }
                          }
                        }'''
        res = self.request_get(self.getSearchUrl(index_name=self.index_name_cla),
                               data=search_json, headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        data = res.json()
        for hits in data['hits']['hits']:
            source_data = hits['_source']
            corporation_admin_added = source_data['corporation'] + "_adminAdded_" + str(source_data['is_admin_added'])
            giteeid_company_dict.update({source_data['employee_id']: corporation_admin_added})

        return giteeid_company_dict

    def getUserInfoFromFile(self):
        if self.is_update_tag_company != 'true':
            return {}

        domain_company_dict = {}
        giteeid_company_dict = {}
        if self.data_yaml_url and self.company_yaml_url:
            cmd = 'wget -N %s' % self.data_yaml_url
            p = os.popen(cmd.replace('=', ''))
            p.read()
            datas = yaml.load_all(open(self.data_yaml_path, encoding='UTF-8')).__next__()

            cmd = 'wget -N %s' % self.company_yaml_url
            p = os.popen(cmd.replace('=', ''))
            p.read()
            companies = yaml.load_all(open(self.company_yaml_path, encoding='UTF-8')).__next__()
            p.close()

            for company in companies['companies']:
                for domain in company['domains']:
                    domain_company_dict.update({domain: company['company_name']})

            for data in datas['users']:
                if data['companies'][0]['company_name'] != '':
                    giteeid_company_dict.update({data['gitee_id']: data['companies'][0]['company_name']})
                elif data['emails']:
                    for email in data['emails']:
                        domain = str(email).split('@')[1]
                        if domain in domain_company_dict:
                            giteeid_company_dict.update({data['gitee_id']: domain_company_dict.get(domain)})
                else:
                    giteeid_company_dict.update({data['gitee_id']: "independent"})

        return giteeid_company_dict

    def users_lower(self):
        users = []
        for user in self.internalUsers:
            if isinstance(user, str) is True:
                user = user.lower()
            users.append(user)
        return users

    def get_company_dict(self):
        giteeid_company_dict_copy = {}
        keys = self.giteeid_company_dict.keys()
        for k in keys:
            if isinstance(k, str) is True:
                k1 = k.lower()
            else:
                k1 = k
            giteeid_company_dict_copy.update({k1: self.giteeid_company_dict.get(k)})
        return giteeid_company_dict_copy

    def getUserInfo(self, login, created_at=None):
        if isinstance(login, str) is True:
            login = login.lower()
        internalUsers_copy = self.users_lower()
        giteeid_company_dict_copy = self.get_company_dict()
        userExtra = {}
        if self.is_gitee_enterprise == 'true':
            if login in self.enterpriseUsers:
                userExtra["tag_user_company"] = self.internal_company_name
                userExtra["is_project_internal_user"] = 1
            else:
                userExtra["tag_user_company"] = "independent"
                userExtra["is_project_internal_user"] = 0
        else:
            if login in internalUsers_copy:
                userExtra["tag_user_company"] = self.internal_company_name
                userExtra["is_project_internal_user"] = 1
            else:
                userExtra["tag_user_company"] = "independent"
                userExtra["is_project_internal_user"] = 0
                tag_user_company = giteeid_company_dict_copy.get(login, 'independent')
                sp = tag_user_company.split("_adminAdded_", 1)
                userExtra["tag_user_company"] = sp[0]
                if len(sp) == 2:
                    userExtra["is_admin_added"] = sp[1]
                else:
                    userExtra["is_admin_added"] = 0

        if created_at and len(self.giteeid_company_change_dict) != 0 and login in self.giteeid_company_change_dict:
            vMap = self.giteeid_company_change_dict[login]
            times = sorted(vMap.keys())
            for i in range(1, len(times) + 1):
                if i == 1:
                    startTime = datetime.strptime('1990-01-01', '%Y-%m-%d')
                else:
                    startTime = datetime.strptime(times[i - 1], '%Y-%m-%d')
                if i == len(times):
                    endTime = datetime.strptime('2222-01-01', '%Y-%m-%d')
                else:
                    endTime = datetime.strptime(times[i], '%Y-%m-%d')
                company = vMap.get(times[i - 1])

                if startTime <= datetime.strptime(created_at[0:10], '%Y-%m-%d') < endTime:
                    userExtra["tag_user_company"] = company
                else:
                    continue

        if userExtra["tag_user_company"] == self.internal_company_name:
            userExtra["is_project_internal_user"] = 1
        else:
            userExtra["is_project_internal_user"] = 0
        
        if self.company_location_index:
            addr = self.getCompanyLocationInfo(userExtra['tag_user_company'], self.company_location_index)
            if addr:
                userExtra.update(addr)
        return userExtra

    def getCompanyLocationInfo(self, company, index):
        query = '''
        {
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "company.keyword": "%s"
                            }
                        }
                    ]
                }
            },
            "size": 10,
            "aggs": {}
        }''' % company
        res = self.request_get(self.getSearchUrl(index_name=index),
                               data=query.encode('utf-8'), headers=self.default_headers)
        if res.status_code != 200:
            print("The index not exist")
            return {}
        data = res.json()
        for hits in data['hits']['hits']:
            source_data = hits['_source']
            loc = {
                    'location': source_data.get('location'),
                    'company_location': source_data.get('company_location'),
                    'innovation_center': source_data.get('innovation_center')
            }
            return loc

    def tagUserOrgChanged(self):
        if len(self.giteeid_company_change_dict) == 0:
            return
        for key, vMap in self.giteeid_company_change_dict.items():
            vMap.keys()
            times = sorted(vMap.keys())
            for i in range(1, len(times) + 1):
                if i == 1:
                    startTime = '1990-01-01'
                else:
                    startTime = times[i - 1]
                if i == len(times):
                    endTime = '2222-01-01'
                else:
                    endTime = times[i]
                company = vMap.get(times[i - 1])
                # is_project_internal_user = 0
                # if company == self.internal_company_name:
                #     is_project_internal_user = 1

                if self.company_location_index:
                    query = self.get_update_loc_info_query(company, startTime, endTime, key)
                else:
                    query = '''{
                    "script": {
                        "source": "ctx._source['tag_user_company']='%s'"
                    },
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "range": {
                                        "created_at": {
                                            "gte": "%s",
                                            "lt": "%s"
                                        }
                                    }
                                },
                                {
                                    "term": {
                                        "user_login.keyword": "%s"
                                    }
                                }
                            ]
                        }
                    }
                }''' % (company, startTime, endTime, key)
                self.updateByQuery(query=query.encode('utf-8'))

    def tagRepoSigChanged(self, repo_sig_dict=None):
        if len(repo_sig_dict) == 0:
            return
        url = "https://gitee.com/"
        if 'opengauss' in self.orgs:
            url = url + 'opengauss/'
        for key in repo_sig_dict:
            gitee_repo = url + key
            sig_names = repo_sig_dict.get(key)
            query_str = '''
            {{
                "script": {{
                    "source": "ctx._source.sig_names=params.sig",
                    "params": {{
                        "sig": {sig_names}
                    }}
                }},
                "query": {{
                    "bool": {{
                        "must": [
                            {{
                                "term": {{
                                    "gitee_repo.keyword": "{gitee_repo}"
                                }}
                            }}
                        ]
                    }}
                }}
            }}'''
            query = query_str.format(sig_names=sig_names, gitee_repo=gitee_repo).replace("'", "\"")
            self.updateByQuery(query=query.encode('utf-8'))
            print(f"update the sig of {gitee_repo} over!")

    def get_update_loc_info_query(self, company, startTime, endTime, user):
        company_info = self.getCompanyLocationInfo(company, self.company_location_index)
        company_location = company_info.get('company_location') if company_info else ''
        innovation_center = company_info.get('innovation_center') if company_info else ''
        loc = company_info.get('location') if company_info else None
        update_json = '''
        {{
            "script": {{
                "source": "ctx._source.tag_user_company = params.tag_user_company;\
                ctx._source.company_location = params.company_location;\
                ctx._source.innovation_center = params.innovation_center;\
                ctx._source.location = params.location",
                "params": {{
                    "tag_user_company": "{}",
                    "company_location": "{}",
                    "innovation_center": "{}",
                    "location": {{
                        "lon": {},
                        "lat": {}
                    }}
                }}
            }},
            "query": {{
                "bool": {{
                    "must": [
                        {{
                            "range": {{
                                "created_at": {{
                                    "gte": "{}",
                                    "lt": "{}"
                                }}
                            }}
                        }},
                        {{
                            "term": {{
                                "user_login.keyword": "{}"
                            }}
                        }}
                    ]
                }}
            }}
        }} '''
        if loc is None:
            update_json = update_json.format(company, company_location, innovation_center, "null",
                                             "null", startTime, endTime, user)
        else:
            update_json = update_json.format(company, company_location, innovation_center,
                                             loc.get('lon'), loc.get('lat'), startTime, endTime, user)
        return update_json

    def getItselfUsers(self, filename="users"):
        try:
            f = open(filename, 'r', encoding="utf-8")
        except:
            return []

        users = []
        for line in f.readlines():
            if line != "\n":
                users.append(line.split('\n')[0])
        return users

    def getEnterpriseUser(self):
        if self.is_gitee_enterprise != "true":
            return

        self.orgs = self.getOrgs(config.get('orgs'))
        client = GiteeClient(self.orgs[0], "", self.gitee_token)

        data = self.getGenerator(client.enterprise_members())
        for d in data:
            user = d.get("user").get("login")
            print(user)
            self.enterpriseUsers.append(user)

    def getOrgs(self, orgsStr):
        orgs = []
        if orgsStr:
            orgs = orgsStr.split(",")
            print(orgs)
        else:
            print("The 'orgs' field must be set")
        return orgs

    def getGenerator(self, response):
        data = []
        try:
            while 1:
                if isinstance(response, types.GeneratorType):
                    res_data = next(response)
                    if isinstance(res_data, str):
                        data += json.loads(res_data.encode('utf-8'))
                    else:
                        data += json.loads(res_data.decode('utf-8'))
                else:
                    data = json.loads(response)
                    break
        except StopIteration:
            return data
        except JSONDecodeError:
            print("Gitee get JSONDecodeError, error: ", response)
        except Exception as ex:
            print('*** Generator fail ***', ex)

        return data

    def safe_put_bulk(self, bulk_json, header=None, url=None):
        """Bulk items to a target index `url`. In case of UnicodeEncodeError,
        the bulk is encoded with iso-8859-1.

        :param url: target index where to bulk the items
        :param bulk_json: str representation of the items to upload
        """
        if not bulk_json:
            return

        _header = {
            "Content-Type": 'application/x-ndjson',
            'Authorization': self.authorization
        }
        if header:
            _header = header

        _url = self.url
        if url:
            _url = url

        total_num = bulk_json.count("\n")
        if total_num > 10000:
            sub_bulk_json = bulk_json.split("\n")
            bulk_json_temp = ''
            for data in sub_bulk_json:
                bulk_json_temp += data + '\n'
                if bulk_json_temp.count('\n') >= 10000:
                    try:
                        res = requests.post(_url + "/_bulk", data=bulk_json_temp.encode('utf-8'),
                                            headers=_header, verify=False)
                        print(res)
                        bulk_json_temp = ""
                        res.raise_for_status()
                    except UnicodeEncodeError:
                        # Related to body.encode('iso-8859-1'). mbox data
                        logger.warning("Encondig error ... converting bulk to iso-8859-1")
                        bulk_json = bulk_json.encode('iso-8859-1', 'ignore')
                        res = requests.put(url, data=bulk_json_temp.encode('utf-8'), headers=_header)
                        res.raise_for_status()
            if bulk_json_temp is not None and bulk_json_temp != '\n' and len(bulk_json_temp) > 0:
                try:
                    res = requests.post(_url + "/_bulk", data=bulk_json_temp.encode('utf-8'),
                                        headers=_header, verify=False)
                    print(res)
                    bulk_json_temp = ""
                    res.raise_for_status()
                except UnicodeEncodeError:
                    # Related to body.encode('iso-8859-1'). mbox data
                    logger.warning("Encondig error ... converting bulk to iso-8859-1")
                    res = requests.put(url, data=bulk_json_temp.encode('utf-8'), headers=_header)
                    res.raise_for_status()
        else:
            try:
                res = requests.post(_url + "/_bulk", data=bulk_json.encode('utf-8'),
                                    headers=_header, verify=False)
                res.raise_for_status()
                print(res)
            except UnicodeEncodeError:
                # Related to body.encode('iso-8859-1'). mbox data
                logger.warning("Enconding error ... converting bulk to iso-8859-1")
                bulk_json = bulk_json.encode('iso-8859-1', 'ignore')
                res = requests.put(url=_url, data=bulk_json, headers=_header)
                res.raise_for_status()
            except Exception as otherError:
                print('Fail to store data to ES!!! Error info:')
                print(otherError.__repr__(), '\n')
                # raise otherError

    def searchEsList(self, index_name, search=None):
        url = self.url + '/' + index_name + '/search'
        data = '''{"size":10000,"query": {"bool": {%s}}}''' % search
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=data.encode('utf-8')).content)
        except:
            print(traceback.format_exc())
        return res['hits']['hits']

    def getRepoMaintainer(self, index_name, repo=None):
        result = {}
        if not index_name:
            return result
        repo = str(repo).replace('/', '\\\/')
        url = self.url + '/' + index_name + '/_search'
        data = '''{
    "size": 0,
    "query": {
        "bool": {
            "filter": [
                
                {
                    "query_string": {
                        "analyze_wildcard": true,
                        "query": "repo_name.keyword:%s"
                    }
                }
            ]
        }
    },
    "aggs": {
        "2": {
            "terms": {
                "field": "committer.keyword",
                "size": 10000,
                "order": {
                    "_key": "desc"
                },
                "min_doc_count": 1
            },
            "aggs": {}
        }
    }
}''' % repo
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=data.encode('utf-8')).content)
        except:
            print(traceback.format_exc())
        maintainerdata = res['aggregations']['2']['buckets']
        if maintainerdata:
            mtstr = ""
            for m in maintainerdata:
                mtstr = mtstr + str(m['key']) + ","
            mtstr = mtstr[:len(mtstr) - 1]
            result['Maintainer'] = mtstr
        return result

    def getCompanys(self, index_name):
        result = []
        if not index_name:
            return result
        url = self.url + '/' + index_name + '/_search'
        data = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "*"
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "2": {
                    "terms": {
                        "field": "tag_user_company.keyword",
                        "size": 1000,
                        "min_doc_count": 1
                    },
                    "aggs": {}
                }
            }
        }'''
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=data.encode('utf-8')).content)
            data = res['aggregations']['2']['buckets']
            for d in data:
                result.append(d['key'])
        except:
            print(traceback.format_exc())
        return result

    def getRepoSigCount(self, index_name, repo=None):
        result = {}
        if not index_name:
            return result
        repo = str(repo).replace('/', '\\\/')
        querystr = '''{
    "size": 0,
    "query": {
        "bool": {
            "filter": [
                {
                    "query_string": {
                        "analyze_wildcard": true,
                        "query": "repo_name.keyword:%s"
                    }
                }
            ]
        }
    },
    "aggs": {
        "2": {
            "terms": {
                "field": "repo_name.keyword",
                "size": 10000,
                "order": {
                    "_key": "desc"
                },
                "min_doc_count": 1
            },
            "aggs": {
                "1": {
                    "cardinality": {
                        "field": "sig_name.keyword"
                    }
                }
            }
        }
    }
}''' % (repo)
        url = self.url + '/' + index_name + '/_search'
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=querystr.encode('utf-8')).content)
            resultdata = res['aggregations']['2']['buckets']
            count = 0
            for re in resultdata:
                count += int(re['1']['value'])
            result['sigcount'] = count
            return result
        except:
            print(traceback.format_exc())
            result['sigcount'] = 0
            return result

    def getRepoSigNames(self, index_name, repo=None):
        if not index_name:
            return ""
        querystr = '''{
    "query": {
        "term":{
        "repo_name.keyword": "%s"
        }
    }
}''' % (repo)
        url = self.url + '/' + index_name + '/_search'
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=querystr.encode('utf-8')).content)
            resultdata = res['hits']['hits']
            restr = ''
            for re in resultdata:
                restr = restr + "," + re['_source']['sig_name']
            tuplelist = restr[1:].split(",")
            tuplelist = list(set(tuplelist))
            resultstr = ""
            for s in tuplelist:
                resultstr = resultstr + ',' + s
            if resultstr != "":
                return resultstr[1:]
            return ""
        except:
            print(traceback.format_exc())
            return ""

    def geTimeofVersion(self, version, repo, index):
        url = self.url + '/' + index + '/_doc/' + repo + version
        try:
            res = self.request_get(url=url, headers=self.default_headers)
            if res.status_code == 404:
                return None
            else:
                content = json.loads(res.content)
                return content['_source']['version_time']
        except:
            print(traceback.format_exc())
            return None

    def post_delete_index_name(self, index_name=None, header=None, url=None):
        if not index_name:
            return

        _header = {
            "Content-Type": 'application/x-ndjson',
            'Authorization': self.authorization
        }
        if header:
            _header = header

        _url = self.url
        if url:
            _url = url

        try:
            res = requests.delete(_url + "/" + index_name, headers=_header, verify=False)
            res.raise_for_status()
            print(res)
        except:
            print(traceback.format_exc())

    def post_delete_delete_by_query(self, bulk_json, index_name, header=None, url=None):
        if not bulk_json:
            return

        if not index_name:
            return

        _header = {
            "Content-Type": 'application/json',
            'Authorization': self.authorization
        }
        if header:
            _header = header

        _url = self.url
        if url:
            _url = url

        try:
            res = requests.post(_url + "/" + index_name + '/_delete_by_query', headers=_header, verify=False,
                                data=bulk_json)
            res.raise_for_status()
            print(res)
        except:
            print(traceback.format_exc())

    def getStartTime(self):
        # 2020-04-29T15:59:59.000Z
        last_time = self.getLastTime()
        if last_time is None:
            return self.from_date
        # 20200429
        last_time = last_time.split("T")[0].replace("-", "")

        f = datetime.strptime(last_time, "%Y%m%d") + timedelta(days=-1)
        # 20200428
        starTime = f.strftime("%Y%m%d")
        return starTime

    def searchEmailGitee(self, url, headers, index_name, search=None, scroll_duration='1m'):
        email_data = []
        if headers is None:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': self.email_gitee_authorization
            }
        es_url = url + '/' + index_name + '/_search?scroll=' + scroll_duration
        search = '''{"size":10000,"query": {"bool": {%s}}}''' % search
        res = self.request_get(url=es_url, headers=headers,
                               data=search.encode('utf-8'))
        if res.status_code != 200:
            print('requests error')
            return None
        res_data = res.json()
        data = res_data['hits']['hits']
        print('scroll data count: %s' % len(data))
        email_data.extend(data)

        scroll_id = res_data['_scroll_id']
        while scroll_id is not None and len(data) != 0:
            es_url = url + '/_search/scroll'
            search = '''{
                          "scroll": "%s",
                          "scroll_id": "%s"
                        }''' % (scroll_duration, scroll_id)
            res = self.request_get(url=es_url, headers=headers,
                                   data=search.encode('utf-8'))
            if res.status_code != 200:
                print('requests error')
                return None
            res_data = res.json()
            scroll_id = res_data['_scroll_id']
            data = res_data['hits']['hits']
            print('scroll data count: %s' % len(data))
            email_data.extend(data)
        print('scroll over')
        return email_data

    def searchEsList(self, index_name, search=None):
        url = self.url + '/' + index_name + '/_search'
        data = '''{"size":10000,"query": {"bool": {%s}}}''' % search
        try:
            res = json.loads(
                self.request_get(url=url, headers=self.default_headers,
                                 data=data.encode('utf-8')).content)
            return res['hits']['hits']
        except:
            print(traceback.format_exc())
            return None

    def getLastFormatTime(self):
        # 2020-04-29T15:59:59.000Z
        last_time = self.getLastTime()
        if last_time is None:
            return self.from_date
        # 20200429
        last_time = last_time.split("T")[0].replace("-", "")

        f = datetime.strptime(last_time, "%Y%m%d")
        lastTime = f.strftime("%Y%m%d")
        return lastTime

    def getLastTime(self, field="created_at"):
        data_agg = '''
                "aggs": {
                    "1": {
                      "max": {
                        "field": "%s"
                      }
                    }
                }
            ''' % field

        data_json = '''
            { "size": 0, %s
            } ''' % data_agg
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The field (%s) not exist." % field)
            return None
        data = res.json()
        # print(data)
        result_num = data['hits']['total']['value']
        if result_num == 0:
            return
        # get min create at value
        created_at_value = data['aggregations']['1']['value_as_string']
        return created_at_value

    def checkFieldExist(self, field="_id", filter=None):
        query_data = '''
                "query": {
                    "terms": {
                      "%s": ["%s"]
                    }
                }
            ''' % (field, filter)

        data_json = '''
            { "size": 0, %s
            } ''' % query_data

        self.default_headers = {
            'Authorization': self.authorization,
            'Content-Type': 'application/json'
        }
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The resource not exist")
            return False
        data = res.json()

        result_num = data['hits']['total']['value']
        if result_num == 0:
            return False
        # get min create at value
        # created_at_value = data['aggregations']['1']['value_as_string']
        return True

    def get_last_item_field(self, field, filters_=[], offset=False):
        """Find the offset/date of the last item stored in the index.
        """
        last_value = None

        if filters_ is None:
            filters_ = []

        terms = []
        for filter_ in filters_:
            if not filter_:
                continue
            term = '''{"term" : { "%s" : "%s"}}''' % (
                filter_['name'], filter_['value'])
            terms.append(term)

        data_query = '''"query": {"bool": {"filter": [%s]}},''' % (
            ','.join(terms))

        data_agg = '''
            "aggs": {
                "1": {
                  "max": {
                    "field": "%s"
                  }
                }
            }
        ''' % field

        data_json = '''
        { "size": 0, %s  %s
        } ''' % (data_query, data_agg)

        print(data_json)

        self.default_headers = {
            'Authorization': self.authorization,
            'Content-Type': 'application/json'
        }
        data = self.request_get(self.getSearchUrl(),
                                data=data_json,
                                headers=self.default_headers)
        res = data.json()
        print(res)

        if "value_as_string" in res["aggregations"]["1"]:
            last_value = res["aggregations"]["1"]["value_as_string"]
            last_value = str_to_datetime(last_value)
        else:
            last_value = res["aggregations"]["1"]["value"]
            if last_value:
                try:
                    last_value = unixtime_to_datetime(last_value)
                except InvalidDateError:
                    last_value = unixtime_to_datetime(last_value / 1000)

        return last_value

    def getSearchUrl(self, url=None, index_name=None):
        if index_name is None:
            index_name = self.index_name

        if url is None:
            url = self.url
        return url + "/" + index_name + "/_search"

    def get_last_date(self, field, filters_=[]):
        """Find the date of the last item stored in the index
        """
        last_date = self.get_last_item_field(field, filters_=filters_)

        return last_date

    def get_incremental_date(self):
        """Field with the date used for incremental analysis."""

        return "updated_at"

    def get_last_update_from_es(self, _filters=[]):
        last_update = self.get_last_date(self.get_incremental_date(), _filters)

        return last_update

    def get_from_date(self, filters=[]):
        last_update = self.get_last_update_from_es(filters)

        # if last_update is None:
        #     last_update = str_to_datetime("2020-04-26T14:26+08:00")
        #
        # print("last update time:", last_update)
        # print("last update time type:", type(last_update))
        return last_update

    def getTotalAuthorName(self, field="user_login.keyword", size=1500):
        data_json = '''{"size": 0,
                     "aggs": {
                         "uniq_gender": {
                             "terms": {
                                 "field": "%s",
                                 "size": %d
                             }
                         }
                     }
                     }''' % (field, size)
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The author name not exist")
            return []
        data = res.json()
        return data['aggregations']['uniq_gender']['buckets']

    def setIsFirstCountributeItem(self, user_login):
        data_query = '''"query": {
            "bool": {
                "must": [
                    {
                        "match": {"user_login.keyword": "%s"}
                    },
                    {
                        "bool": {
                            "should": [
                                {"match": {"is_gitee_pull_request": 1}},
                                {"match": {"is_gitee_issue": 1}},
                                {"match": {"is_gitee_issue_comment": 1}},
                                {"match": {"is_gitee_review_comment": 1}},
                                {"match": {"is_gitee_comment": 1}},
                                {"match": {"is_gitee_fork": 1}}
                            ]
                        }
                        }
                    ]
                }
            },''' % (user_login)
        data_agg = '''
                "aggs": {
                    "1": {
                      "min": {
                        "field": "created_at"
                      }
                    }
                }
            '''

        data_json = '''
            { "size": 2, %s  %s
            } ''' % (data_query, data_agg)
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        res = res.json()
        result_num = res['hits']['total']['value']
        if result_num == 0:
            print("author name(%s) not exist." % (user_login))
            return
        # get min create at value
        created_at_value = res['aggregations']['1']['value_as_string']

        # get author name item id with min created_at
        data_json = '''{"size": 1, "query": {"bool": {"must": [{"match": {"user_login.keyword": "%s"}}, {"match": {"created_at": "%s"}}]}}}''' % (
            user_login, created_at_value)
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)

        if res.status_code != 200:
            print("get user(%s) id  fail" % user_login)
            return
        res = res.json()
        id = res['hits']['hits'][0]['_id']

        if "_star" in id or "_watch" in id:
            return

        update_data = '''{
            "doc": {
                "is_first_contribute": 1
            }
        }'''
        url = self.url + "/" + self.index_name + '/_update/' + quote(id, safe='')
        res = requests.post(url, data=update_data,
                            headers=self.default_headers, verify=False)
        if res.status_code != 200:
            print("update user name fail:", res.text)
            return
        print("update user(%s) id(%s) is_first_contribute  success" % (user_login, id))

    def updateRepoCreatedName(self, org_name, repo_name, author_name, user_login, is_internal=False):
        data_query = '''"query": {"bool": {"must": [{"match": {"is_gitee_repo": 1}},{"match": {"repository.keyword": "%s"}}]}}''' % (
                org_name + "/" + repo_name)

        data_json = '''
        { "size": 1, %s
        } ''' % (data_query)

        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            return
        res = res.json()
        result_num = res['hits']['total']['value']
        if result_num != 1:
            print("repo(%s) not exist or has more than one resources." % (
                    org_name + "/" + repo_name))
            return

        id = res['hits']['hits'][0]['_id']
        if not id:
            print("ID not exist")
            return

        original_author_name = res['hits']['hits'][0]['_source'][
            'author_name']
        if original_author_name == author_name:
            print("the repo(%s) author name(%s) is the same as community record" %
                  (org_name + "/" + repo_name, author_name))
            return

        print("Change repo(%s) author name from (%s) to (%s)" %
              (org_name + "/" + repo_name, original_author_name, author_name))
        update_data = {
            "doc": {
                "author_name": author_name,
                "user_login": user_login
            }
        }
        if is_internal == True:
            update_data["doc"]["is_project_internal_user"] = 1
            update_data["doc"]["tag_user_company"] = self.internal_company_name
        else:
            update_data["doc"]["is_project_internal_user"] = None
            update_data["doc"]["tag_user_company"] = None
        self.update(id, update_data)

    def update(self, id, update_data):
        url = self.url + "/" + self.index_name + '/_update/' + quote(id,
                                                                     safe='')
        res = requests.post(url, data=json.dumps(update_data),
                            headers=self.default_headers, verify=False)
        if res.status_code != 200:
            print("update repo author name failed:", res.text)
            return

    def reindex(self, reindex_json, query_es=None, es_authorization=None):
        url = self.url + '/' + '_reindex'
        _headers = self.default_headers
        if query_es is not None and es_authorization is not None:
            url = query_es + '/' + '_reindex'
            _headers = {
                'Content-Type': 'application/json',
                'Authorization': es_authorization
            }
        res = requests.post(url, headers=_headers, verify=False, data=reindex_json)
        if res.status_code != 200:
            return 0
        data = res.json()
        data_total = data['total']
        return data_total

    def get_sig_maintainers(self, index_name):
        search_json = '''{
                      "size": 0,
                      "aggs": {
                        "maintainers": {
                          "terms": {
                            "field": "maintainers.keyword",
                            "size": 10000
                          }
                        }
                      }
                    }'''
        maintainers = []
        url = self.url + "/" + index_name + '/_search'
        res = requests.post(url, headers=self.default_headers, verify=False, data=search_json)
        if res.status_code != 200:
            return maintainers
        data = res.json()
        for bucket in data["aggregations"]['maintainers']['buckets']:
            maintainers.append(bucket['key'])
        return maintainers

    def updateByQuery(self, query, index=None, query_es=None, es_authorization=None):
        if index is None:
            index = self.index_name
        url = self.url + '/' + index + '/_update_by_query?conflicts=proceed'
        _headers = self.default_headers

        if query_es is not None and es_authorization is not None:
            url = query_es + '/' + index + '/_update_by_query?conflicts=proceed'
            _headers = {
                'Content-Type': 'application/json',
                'Authorization': es_authorization
            }
        res = requests.post(url, headers=_headers, verify=False, data=query)
        if res.status_code != 200:
            print('update by query error, ', res.text)

    def getUniqueCountByDate(self, field, from_date, to_date,
                             url=None, index_name=None):
        data_json = '''{"size": 0,
         "query": {
             "range": {
                 "created_at": {
                     "gte": "%s",
                     "lte": "%s"
                 }
             }
         },
         "aggs": {
             "sum": {
                 "cardinality": {
                     "field": "%s"
                 }
             }
         }
         }''' % (from_date, to_date, field)

        res = self.request_get(self.getSearchUrl(url, index_name), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The field (%s) not exist from time(%s) to (%s)"
                  % (field, from_date, to_date))
            return None

        data = res.json()
        # print(data["aggregations"]["sum"]["value"])
        return data["aggregations"]["sum"]["value"]

    def giteeEventMaxId(self, repo_full_name):
        data_json = '''{
              "size": 0,
              "query": {
                "bool": {
                  "must": [
                    {
                      "term": {
                        "repo.full_name.keyword": "%s"
                      }
                    }
                  ]
                }
              },
              "aggs": {
                "max_id": {
                  "max": {
                    "field": "id"
                  }
                }
              }
            }''' % repo_full_name
        self.setFirstItem()
        res = self.request_get(self.getSearchUrl(index_name=self.index_name), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            return 0
        max_id = res.json()['aggregations']['max_id']['value']
        if max_id is None or max_id == 'null':
            return 0
        return max_id

    def getCountByTermDate(self, term=None, field=None, from_date=None, to_date=None,
                           url=None, index_name=None, query=None, query_index_name=None, origin=None):
        if query:
            if origin == 'qinghua':
                agg_json = '''"aggs": {"2": {"sum": {"field": "%s"}}}''' % field
            elif field:
                agg_json = '''"aggs": {"2": {"terms": {"field": "%s","size": 100000,"min_doc_count": 1}}}''' % field
            else:
                agg_json = '''"aggs": {"2": {"date_histogram": {"interval": "100000d","field": "created_at","min_doc_count": 0}}}'''

            data_json = '''{
                "size": 0,
                "query": {
                    "bool":{
                        "filter":[
                            {"range": {
                                "created_at": {
                                    "gte": "%s",
                                    "lte": "%s"
                                }
                            }},
                            {"query_string":{
                                "analyze_wildcard":true,
                                "query": "%s"
                            }}]
                    }
                },
                %s
            }''' % (from_date, to_date, query, agg_json)
        elif term:
            data_json = '''{
                "size": 3,
                "query": {
                    "range": {
                        "created_at": {
                            "gte": "%s",
                            "lte": "%s"
                        }
                    }
                },
                "aggs": {
                    "list": {
                        "terms": {
                            "field": "%s"
                        },
                        "aggs": {
                            "sum": {
                                "sum": {
                                    "field": "%s"
                                }
                            }
                        }
                    }
                }
            }''' % (from_date, to_date, term, field)
        else:
            data_json = '''{
                "size": 0,
                "query": {
                    "range": {
                        "created_at": {
                            "gte": "%s",
                            "lte": "%s"
                        }
                    }
                },
                "aggs": {
                    "sum": {
                        "sum": {
                            "field": "%s"
                        }
                    }
                }
            }''' % (from_date, to_date, field)

        if query_index_name is None:
            query_index_name = index_name

        if self.item == "openeuler_download_ip_count":
            data_json = '''{
                              "size": 0,
                              "query": {
                                "bool": {
                                  "filter": [
                                    {
                                      "range": {
                                        "created_at": {
                                          "gte": "%s",
                                          "lte": "%s"
                                        }
                                      }
                                    },
                                    {
                                      "query_string": {
                                          "analyze_wildcard": true,
                                          "query": "%s"
                                        }
                                    }
                                  ]
                                }
                              },
                              "aggs": {
                                "count": {
                                  "cardinality": {
                                    "field": "%s"
                                  }
                                }
                              }
                            }''' % (from_date, to_date, query, field)
            return self.getCardinalityIpCount(url, query_index_name, data_json, field, from_date, to_date)

        res = self.request_get(self.getSearchUrl(url, query_index_name), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The field (%s) not exist from time(%s) to (%s), err=%s"
                  % (field, from_date, to_date, res))
            return None

        data = res.json()
        count = 0
        if query:
            if origin == 'qinghua':
                count = data["aggregations"]["2"]["value"]
            elif not field:
                for bucket in data["aggregations"]["2"]["buckets"]:
                    count += bucket["doc_count"]
            else:
                count = len(data["aggregations"]["2"]["buckets"])

        elif term is None:
            count = data["aggregations"]["sum"]["value"]
        else:
            for b in data["aggregations"]["list"]["buckets"]:
                count += b["sum"]["value"]
        # count = data["aggregations"]["sum"]["value"]
        # print(count)
        return count

    def getCardinalityIpCount(self, url, query_index_name, data_json, field=None, from_date=None, to_date=None):
        res = self.request_get(self.getSearchUrl(url, query_index_name), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("The field (%s) not exist from time(%s) to (%s), err=%s"
                  % (field, from_date, to_date, res))
            return None

        data = res.json()
        return data["aggregations"]["count"]["value"]


    def getCountByDateRange(self, matchs, from_date, to_date, interval=1):
        terms = []
        for match in matchs:
            if not match:
                continue
            term = '''{"match" : { "%s" : %d}}''' % (
                match['name'], match['value'])
            terms.append(term)

        data_query = '''"query": {"bool": {"must": [%s]}},''' % (
            ','.join(terms))

        # "aggs":{
        #     "range": {
        #         "date_range": {
        #             "field": "created_at",
        #             "ranges": [
        #                 {"from": "2019-01-07T00:00:00+08:00",
        #                  "to": "2020-06-09T23:00:00+08:00"},
        #                 {"from": "2019-01-07T00:00:00+08:00",
        #                  "to": "2020-06-08T00:00:00+08:00"},
        #                 {"from": "2019-01-07T00:00:00+08:00",
        #                  "to": "2020-06-07T00:00:00+08:00"}
        #             ]
        #         }
        #     }
        # }
        ranges = []
        tmp_date = from_date
        while 1:
            if tmp_date > to_date:
                break

            term = '''{"from" : "%s", "to": "%s"}''' % (
                from_date.strftime("%Y-%m-%dT00:00:00+08:00"), tmp_date.strftime("%Y-%m-%dT23:59:59+08:00"))
            ranges.append(term)
            tmp_date = tmp_date + timedelta(days=interval)

        data_agg = '''
                "aggs": {
                    "range": {
                      "date_range": {
                        "field": "created_at",
                        "ranges": [%s]
                      }
                    }
                }
            ''' % ','.join(ranges)

        data_json = '''
            { "size": 0, %s  %s
            } ''' % (data_query, data_agg)

        print(data_json)
        res = self.request_get(self.getSearchUrl(), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("Get result error:", res.status_code)
            return None

        data = res.json()
        data = data.get("aggregations").get("range").get("buckets")
        return data

    def initLocationGeoIPIndex(self):
        body = {
            "description": "Add geoip info",
            "processors": [
                {
                    "geoip": {
                        "field": "ip"
                    }
                }
            ]
        }

        url = self.url + "/_ingest/pipeline/geoip"
        response = requests.request("PUT", url, headers=self.default_headers, data=json.dumps(body), verify=False)
        if response.status_code != 200:
            return None

    @globalExceptionHandler
    def getLocationByIP(self, ip):
        # initLocationGeoIPIndex()
        payload = "{\n\t\"ip\": \"%s\"\n}" % ip
        r = requests.put(self.url + '/my_index/_doc/my_id?pipeline=geoip',
                         data=payload, headers=self.default_headers,
                         verify=False)
        if r.status_code != 200:
            print("get location failed, err=", r.text)
            return {}

        res = self.request_get(self.url + '/my_index/_doc/my_id',
                               headers=self.default_headers)
        if r.status_code != 200:
            print("get location failed, err=", r.text)
            return {}
        '''
        "geoip": {
                "continent_name": "Asia",
                "region_iso_code": "CN-ZJ",
                "city_name": "Hangzhou",
                "country_iso_code": "CN",
                "region_name": "Zhejiang",
                "location": {
                    "lon": 120.1614,
                    "lat": 30.2936
                }
            },
            "ip": "122.235.249.147"
        '''
        j = res.json()
        data = j['_source'].get('geoip')

        if data is None:
            return {}
        return data

    @globalExceptionHandler
    def get_ip_location(self, ip):
        data_json = '''{"query":{"bool":{"must":[{"match":{"ip.keyword":"%s"}}]}},"aggs":{}}''' % ip
        res = self.request_get(self.getSearchUrl(index_name='ip.location'), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("Get result error:", res.status_code)
            return {}
        try:
            j = res.json().get('hits').get('hits')[0]
            data = j['_source'].get('geoip')
            if data is None:
                return {}
            return data
        except:
            return {}

    @globalExceptionHandler
    def get_ds_ip_location(self, ip):
        params = {'ip': ip}
        res = self.request_get(url=IP_API_URL, params=params, timeout=60)
        if res.status_code != 200:
            return {}
        data = res.json().get('geoip')
        if data is None:
            return {}
        return data

    @globalExceptionHandler
    def getLocationbyCity(self, addr):
        user_agent = str(addr.encode()) + 'application'
        gps = Nominatim(user_agent=user_agent)
        # gps.headers.update({'Connection': 'close'})
        gps.adapter.session.verify = False
        location = gps.geocode(addr)
        if location is None:
            return
        lon = location.longitude
        lat = location.latitude
        res = {
            'lon': lon,
            'lat': lat
        }
        loc = {'location': res}
        return loc

    def getItemsByMatchs(self, matchs, size=500, aggs=None, matchs_not=None):
        '''
        {
            "size": 497,
            "query": {
                "bool": {
                    "must": [
                        {"match":
                            {
                                "is_gitee_fork": 1
                            }
                        },
                        {"match":
                            {
                                "gitee_repo.keyword": "https://gitee.com/mindspore/mindspore"
                            }
                        }
                    ]
                }
            }
        }
        '''
        if matchs is None:
            matchs = []
        if matchs_not is None:
            matchs_not = []

        terms = []
        for match in matchs:
            if not match:
                continue
            term = '''{"match" : { "%s" : "%s"}}''' % (match['name'], match['value'])
            terms.append(term)
        terms_not = []
        for match_not in matchs_not:
            if not match_not:
                continue
            term_not = '''{"match" : { "%s" : "%s"}}''' % (match_not['name'], match_not['value'])
            terms_not.append(term_not)

        data_query = '''"query": {"bool": {"must": [%s], "must_not":[%s]}}''' % (','.join(terms), ','.join(terms_not))

        if aggs:
            data_json = '''
            { "size": %d, %s, %s
            } ''' % (size, data_query, aggs)
        else:
            data_json = '''
            { "size": %d, %s
            } ''' % (size, data_query)
        data = self.request_get(self.getSearchUrl(),
                                data=data_json.encode('utf-8'),
                                headers=self.default_headers)
        if data.status_code != 200:
            print("match data failed, err=", data.text)
            return {}
        res = data.json()
        return res

    def updateToRemoved(self, id):
        update_data = '''{
                    "doc": {
                        "is_removed": 1
                    }
                }'''
        url = self.url + "/" + self.index_name + '/_update/' + quote(id, safe='')
        res = requests.post(url, data=update_data,
                            headers=self.default_headers, verify=False)
        if res.status_code != 200:
            print("set fork is_removed value to 1 fail:", res.text)
            return
        print("set fork is_removed value to 1 success")

    def splitMixDockerHub(self, from_date, count_key, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            id_key = time.mktime(fromTime.timetuple()) * 1000
            data_json = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "metadata__updated_on": {
                                    "lte": "%s"
                                }
                            }
                        },
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "%s"
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "3": {
                    "terms": {
                        "field": "id.keyword",
                        "size": 10,
                        "order": {
                            "_key": "desc"
                        },
                        "min_doc_count": 1
                    },
                    "aggs": {
                        "maxCount": {
                            "max": {
                                "field": "%s"
                            }
                        }
                    }
                }
            }
        }''' % (fromTime.strftime("%Y-%m-%dT23:59:59+08:00"), query, count_key)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            buckets_data = data['aggregations']['3']['buckets']
            fromTime += relativedelta(days=1)
            if len(buckets_data) == 0:
                time_count_dict.update({id_key: 0})
                continue
            for bucket_data in buckets_data:
                max_count = bucket_data['maxCount']['value']
                if not max_count:
                    max_count = 0
                if id_key in time_count_dict:
                    max_count += time_count_dict.get(id_key)
                time_count_dict.update({id_key: max_count})

        res_dict = self.get_day_download(time_count_dict, to)
        return res_dict

    def getTotalRepoDownload(self, from_date, count_key, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            id_key = time.mktime(fromTime.timetuple()) * 1000
            data_json = '''{
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "created_at": {
                                        "lte": "%s"
                                    }
                                }
                            },
                            {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "%s"
                            }
                        }
                        ]
                    }
                },
                "aggs": {
                    "max_download": {
                        "max": {
                            "field": "%s"
                        }
                    }
                }
            }''' % (fromTime.strftime("%Y-%m-%dT23:59:59+08:00"), query, count_key)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            value = data['aggregations']['max_download']['value']
            fromTime += relativedelta(days=1)
            if not value:
                time_count_dict.update({id_key: 0})
                continue
            if id_key in time_count_dict:
                value += time_count_dict.get(id_key)
            time_count_dict.update({id_key: value})

        res_dict = self.get_day_download(time_count_dict, to)
        return res_dict

    def getTotalOepkgsDown(self, from_date, count_key, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            id_key = time.mktime(fromTime.timetuple()) * 1000
            data_json = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "created_at": {
                                    "lte": "%s"
                                }
                            }
                        },
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "%s"
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "repo": {
                    "terms": {
                        "field": "repository_name.keyword",
                        "size": 10000,
                        "order": {
                            "_key": "desc"
                        },
                        "min_doc_count": 1
                    },
                    "aggs": {
                        "maxCount": {
                            "max": {
                                "field": "%s"
                            }
                        }
                    }
                }
            }
        }''' % (fromTime.strftime("%Y-%m-%dT23:59:59+08:00"), query, count_key)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            buckets_data = data['aggregations']['repo']['buckets']
            fromTime += relativedelta(days=1)
            if len(buckets_data) == 0:
                time_count_dict.update({id_key: 0})
                continue
            for bucket_data in buckets_data:
                max_count = bucket_data['maxCount']['value']
                if max_count is None:
                    max_count = 0
                if id_key in time_count_dict:
                    max_count += time_count_dict.get(id_key)
                time_count_dict.update({id_key: max_count})

        res_dict = self.get_day_download(time_count_dict, to)
        return res_dict

    def getTotalImageDown(self, from_date, count_key, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            id_key = time.mktime(fromTime.timetuple()) * 1000
            data_json = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "created_at": {
                                    "gte": "%s",
                                    "lte": "%s"
                                }
                            }
                        },
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "%s"
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "unique": {
                    "terms": {
                        "field": "unique.keyword",
                        "size": 10000,
                        "order": {
                            "_key": "desc"
                        },
                        "min_doc_count": 1
                    },
                    "aggs": {
                        "maxCount": {
                            "max": {
                                "field": "%s"
                            }
                        }
                    }
                }
            }
        }''' % (fromTime.strftime("%Y-%m-%d"), fromTime.strftime("%Y-%m-%d"), query, count_key)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            buckets_data = data['aggregations']['unique']['buckets']
            fromTime += relativedelta(days=1)
            if len(buckets_data) == 0:
                time_count_dict.update({id_key: 0})
                continue
            sum_count = 0
            for bucket_data in buckets_data:
                max_count = bucket_data['maxCount']['value']
                if not max_count:
                    max_count = 0
                sum_count += max_count
            time_count_dict[id_key] = sum_count

        res_dict = self.get_day_download(time_count_dict, to)
        return res_dict

    def getTotalXiheDown(self, from_date, count_key, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        query = '*' if query is None else query
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            stepTime = fromTime + relativedelta(days=1)
            id_key = time.mktime(fromTime.timetuple()) * 1000
            data_json = '''{
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "update_time": {
                                        "gte": "%s",
                                        "lte": "%s"
                                    }
                                }
                            },
                            {
                                "query_string": {
                                    "analyze_wildcard": true,
                                    "query": "%s"
                                }
                            }
                        ]
                    }
                },
                "aggs": {
                    "maxCount": {
                        "max": {
                            "field": "download"
                        }
                    },
                    "maxModel": {
                        "max": {
                            "field": "bigmodel"
                        }
                    },
                    "maxCpu": {
                        "max": {
                            "field": "cloud/cpu"
                        }
                    },
                    "maxNpu": {
                        "max": {
                            "field": "cloud/npu"
                        }
                    }
                }
            }''' % (fromTime.strftime("%Y-%m-%dT00:00:00+08:00"),
                stepTime.strftime("%Y-%m-%dT00:00:00+08:00"),
                query)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            max_count = ((data['aggregations']['maxCount']['value'] or 0)
                         + (data['aggregations']['maxModel']['value'] or 0)
                         + (data['aggregations']['maxCpu']['value'] or 0)
                         + (data['aggregations']['maxNpu']['value'] or 0))
            fromTime += relativedelta(days=1)
            if id_key in time_count_dict:
                max_count += time_count_dict.get(id_key)
            time_count_dict.update({id_key: max_count})

        res_dict = self.get_day_download(time_count_dict, to)
        return res_dict

    def getOpenMindModelDown(self, from_date, count_key=None, query=None, query_index_name=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")
        query = '*' if query is None else query
        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            created_at = fromTime.strftime("%Y-%m-%dT23:59:59+08:00")
            if fromTime.strftime("%Y%m%d") == to:
                created_at = fromTime.strftime("%Y-%m-%dT00:00:01+08:00")
            data_json = '''{
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "created_at": {
                                        "gte": "%s",
                                        "lte": "%s"
                                    }
                                }
                            },
                            {
                                "query_string": {
                                    "analyze_wildcard": true,
                                    "query": "%s"
                                }
                            }
                        ]
                    }
                },
                "aggs": {
                    "git": {
                        "sum": {
                            "field": "is_git_clone"
                        }
                    },
                    "web": {
                        "sum": {
                            "field": "is_web_download"
                        }
                    }
                }
            }''' % (fromTime.strftime("%Y-%m-%d"),
                fromTime.strftime("%Y-%m-%d"),
                query)

            res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                                   headers=self.default_headers)
            if res.status_code != 200:
                return {}
            data = res.json()
            git_count = data['aggregations']['git']['value']
            web_count = data['aggregations']['web']['value']
            count = git_count + web_count // 2
            fromTime += relativedelta(days=1)
            time_count_dict.update({created_at: count})

        return time_count_dict

    def get_day_download(self, time_count_dict, to):
        last_not_0_count = 0
        count_dict = {}
        for key, value in time_count_dict.items():
            dt = time.strftime("%Y%m%d", time.localtime(key / 1000))
            created_at = datetime.strptime(dt, "%Y%m%d").strftime("%Y-%m-%dT23:59:59+08:00")
            if dt == to:
                created_at = datetime.strptime(dt, "%Y%m%d").strftime("%Y-%m-%dT00:00:01+08:00")
            before_value = time_count_dict.get(key - 86400000)

            if before_value is None:
                continue
            if value == 0:
                count_dict.update({created_at: value})
            elif before_value != 0:
                count_dict.update({created_at: value - before_value})
                last_not_0_count = value
            else:
                count_dict.update({created_at: value - last_not_0_count})
        return count_dict

    def getTotalCountMix(self, from_date, count_key,
                         field=None, query=None, origin=None):
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")

        time_count_dict = {}
        while fromTime.strftime("%Y%m%d") <= to:
            created_at = fromTime.strftime("%Y-%m-%dT23:59:59+08:00")
            if fromTime.strftime("%Y%m%d") == to:
                created_at = fromTime.strftime("%Y-%m-%dT00:00:01+08:00")
            count = self.getCountByTermDate(
                term=field,
                field=count_key,
                from_date=fromTime.strftime("%Y-%m-%d"),
                to_date=fromTime.strftime("%Y-%m-%d"),
                index_name=self.index_name,
                query_index_name=self.query_index_name,
                query=query,
                origin=origin)
            if not count:
                count = 0
            time_count_dict.update({created_at: count})
            fromTime = fromTime + timedelta(days=1)
        return time_count_dict

    def writeMixDownload(self, time_count_dict, item, oversea=None, origin=None):
        actions = ''
        for key, value in time_count_dict.items():
            user = {
                item: value,
                "created_at": key,
                "is_%s" % item: 1
            }
            id = key.split("T")[0] + item
            if origin:
                user.update({"is_%s" % origin: 1})
                user.update({"origin": origin})
                id = id + origin
            if oversea and oversea == 'true':
                user.update(({"is_oversea": 1}))
                id = id + '_oversea'
                if origin == 'huawei_cloud':
                    user.update(({item: value * 0.1}))
            else:
                user.update(({"is_oversea": 0}))
                id = id + '_not_oversea'
                if origin == 'huawei_cloud':
                    user.update(({item: value * 0.9}))
            action = getSingleAction(self.index_name, id, user)
            actions += action
        self.safe_put_bulk(actions)

    def writeFirstDownload(self, ip_time_dict):
        actions = ''
        for key, value in ip_time_dict.items():
            user = {
                "ip": key,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.localtime(value)),
                "is_first_download": 1
            }
            action = getSingleAction(self.index_name, key, user)
            actions += action
        self.safe_put_bulk(actions)

    def setToltalCount(self, from_date, count_key, field=None, query=None, key_prefix=""):
        starTime = datetime.strptime(from_date, "%Y%m%d")
        fromTime = datetime.strptime(from_date, "%Y%m%d")
        to = datetime.today().strftime("%Y%m%d")

        actions = ""
        while fromTime.strftime("%Y%m%d") <= to:
            # print(fromTime)

            created_at = fromTime.strftime("%Y-%m-%dT23:59:59+08:00")
            if fromTime.strftime("%Y%m%d") == to:
                created_at = fromTime.strftime("%Y-%m-%dT00:00:01+08:00")
            c = self.getCountByTermDate(
                field,
                count_key,
                starTime.strftime("%Y-%m-%dT00:00:00+08:00"),
                fromTime.strftime("%Y-%m-%dT23:59:59+08:00"),
                index_name=self.index_name,
                query_index_name=self.query_index_name,
                query=query)
            if c is not None:
                user = {
                    "all_" + key_prefix + count_key: c,
                    "updated_at": fromTime.strftime(
                        "%Y-%m-%dT00:00:00+08:00"),
                    "created_at": created_at,
                    # "metadata__updated_on": fromTime.strftime("%Y-%m-%dT23:59:59+08:00"),
                    "is_all" + key_prefix + count_key: 1,
                    "is_removed": 1
                }
                id = fromTime.strftime(
                    "%Y-%m-%dT00:00:00+08:00") + "all_removed" + key_prefix + count_key
                action = getSingleAction(self.index_name, id, user)
                actions += action

            if query is not None:
                query_removed = "(" + query + ") AND !is_removed:1"
            else:
                query_removed = "!is_removed:1"
            c_removed = self.getCountByTermDate(
                field,
                count_key,
                starTime.strftime("%Y-%m-%dT00:00:00+08:00"),
                fromTime.strftime("%Y-%m-%dT23:59:59+08:00"),
                index_name=self.index_name,
                query_index_name=self.query_index_name,
                query=query_removed)
            if c_removed is not None:
                user_removed = {
                    "all_" + key_prefix + count_key: c_removed,
                    "updated_at": fromTime.strftime(
                        "%Y-%m-%dT00:00:00+08:00"),
                    "created_at": created_at,
                    "is_all" + key_prefix + count_key: 1
                }
                id_removed = fromTime.strftime(
                    "%Y-%m-%dT00:00:00+08:00") + "all_" + key_prefix + count_key
                action_removed = getSingleAction(self.index_name, id_removed, user_removed)
                actions += action_removed

            fromTime = fromTime + timedelta(days=1)
        self.safe_put_bulk(actions)

    def getEsIds(self, index_name):
        search_json = '''{
                            "size": 10000,
                            "_source": false,
                            "query": {
                              "match_all": {}
                            }
                          }'''
        res = requests.post(self.getSearchUrl(index_name=index_name), data=search_json, headers=self.default_headers,
                            verify=False)
        if res.status_code != 200:
            print("The search not exist")
            return []

        ids = []
        data = res.json()
        for hit in data['hits']['hits']:
            ids.append(hit['_id'])

        return ids

    def deleteById(self, id, index_name):
        search_json = '''{
                           "query": {
                             "bool": {
                               "must": [
                                 {
                                   "term": {
                                     "_id": "%s"
                                   }
                                 }
                               ]
                             }
                           }
                         }''' % id
        self.post_delete_delete_by_query(index_name=index_name, bulk_json=search_json.encode("utf-8"))

    def getFirstItemByKey(self, query=None, key=None, query_index_name=None):
        data_json = '''{
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"query_string": {
                            "analyze_wildcard": true,
                            "query": "%s"
                        }}]
                }
            },
            "aggs": {
                "group_by_login": {
                "terms": {
                    "field": "%s",
                    "size": 100000
                },
                "aggs": {
                    "login_start": {"top_hits": {"size": 1, "sort": [{"created_at": {"order": "asc"}}]}}

                }
            }}
        }''' % (query, key)

        if query_index_name is None:
            query_index_name = self.index_name
        res = self.request_get(self.getSearchUrl(index_name=query_index_name), data=data_json,
                               headers=self.default_headers)
        if res.status_code != 200:
            print("get First Item By Key(%s), err=%s"
                  % (key, res))
            return None

        data = res.json()

        buckets = data["aggregations"]["group_by_login"]["buckets"]
        if len(buckets) == 0:
            return None
        return buckets

    def getFirstItemMix(self, key_prefix=None, query=None, key=None, query_index_name=None):
        if not key:
            return
        buckets = self.getFirstItemByKey(query, key, query_index_name)
        if not buckets:
            return

        ip_first_dict = {}
        for items in buckets:
            item = items["login_start"]["hits"]["hits"]
            if len(item) == 0:
                continue
            else:
                ip = item[0].get("_source").get("ip")
                created_at = parser.parse(item[0].get("_source").get("created_at")).timestamp()
                ip_first_dict.update({ip: created_at})
        return ip_first_dict

    def setFirstItem(self, key_prefix=None, query=None, key=None, query_index_name=None):
        actions = ""
        users = []
        if not key:
            return
        buckets = self.getFirstItemByKey(query, key, query_index_name)
        if not buckets:
            return
        for items in buckets:
            item = items["login_start"]["hits"]["hits"]
            if len(item) == 0:
                continue
            users.append(item[0])
        query_removed = "(" + query + ") AND !is_removed:1"
        buckets = self.getFirstItemByKey(query_removed, key, query_index_name)
        if not buckets:
            return
        for items in buckets:
            item = items["login_start"]["hits"]["hits"]
            if len(item) == 0:
                continue
            users.append(item[0])
        for u in users:
            user = {
                "user_login": u.get("_source").get("user_login"),
                "tag_user_company": u.get("_source").get("tag_user_company"),
                "is_project_internal_user": u.get("_source").get("is_project_internal_user"),
                "updated_at": u.get("_source").get("updated_at"),
                "created_at": u.get("_source").get("created_at"),
                "is_first" + key_prefix + key: 1
            }
            if "is_removed" in u.get("_source"):
                user.update({"is_removed": 1})
                org_name = self.getFieldNameByLogin(u.get("_source").get("user_login"),
                                                  query, query_index_name, "org_name.keyword")
                gitee_repo = self.getFieldNameByLogin(u.get("_source").get("user_login"),
                                                    query, query_index_name, "gitee_repo.keyword")
                user.update({"org_name": org_name})
                user.update({"gitee_repo": gitee_repo})
            else:
                org_name = self.getFieldNameByLogin(u.get("_source").get("user_login"),
                                                  query_removed, query_index_name, "org_name.keyword")
                gitee_repo = self.getFieldNameByLogin(u.get("_source").get("user_login"),
                                                    query_removed, query_index_name, "gitee_repo.keyword")
                user.update({"org_name": org_name})
                user.update({"gitee_repo": gitee_repo})
            if key:
                gitee_id = key.split(".keyword")[0]
                id = str(u["_source"].get(gitee_id)) + "_is" + key_prefix
            else:
                id = str(u.get("_id")) + "_is" + key_prefix
            action = getSingleAction(self.index_name, id, user)
            actions += action

        self.safe_put_bulk(actions)
        print(key_prefix, 'collect over...')

    def getFieldNameByLogin(self, login, query, query_index, field):
        query_json = '''{
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "user_login.keyword": "%s"
                            }
                        },
                        {
                            "query_string": {
                                "query": "%s"
                            }                       
                        }
                    ],
                    "must_not": [],
                    "should": []
                }
            },
            "aggs": {
                "2": {
                    "terms": {
                        "field": "%s",
                        "size": 10000,
                        "order": {
                            "_key": "desc"
                        },
                        "min_doc_count": 1
                    },
                    "aggs": {}
                }
            }
        }''' % (login, query, field)
        if query_index is None:
            query_index = self.index_name
        res = requests.get(self.getSearchUrl(index_name=query_index), data=query_json,
                           headers=self.default_headers, verify=False, timeout=60)
        if res.status_code != 200:
            print("get field name By Key(%s), err=%s" % (login, res))
            return None
        field_data = res.json()
        buckets = field_data["aggregations"]["2"]["buckets"]
        if len(buckets) == 0:
            return None
        fields = []
        for bucket in buckets:
            fields.append(bucket['key'])
        # print('user contributed in orgs: ', orgs)
        return fields

    def scrollSearch(self, index_name, search=None, scroll_duration='1m', func=None):
        url = self.url + '/' + index_name + '/_search?scroll=' + scroll_duration
        res = self.request_get(url=url, headers=self.default_headers,
                               data=search.encode('utf-8'))
        if res.status_code != 200:
            print('requests error', res.text)
            return
        res_data = res.json()
        data = res_data['hits']['hits']
        print('scroll data count: %s' % len(data))
        func(data)

        scroll_id = res_data['_scroll_id']
        while scroll_id is not None and len(data) != 0:
            url = self.url + '/_search/scroll'
            search = '''{
                          "scroll": "%s",
                          "scroll_id": "%s"
                        }''' % (scroll_duration, scroll_id)
            res = self.request_get(url=url, headers=self.default_headers,
                                   data=search.encode('utf-8'))
            if res.status_code != 200:
                print('requests error')
            res_data = res.json()
            scroll_id = res_data['_scroll_id']
            data = res_data['hits']['hits']
            print('scroll data count: %s' % len(data))
            func(data)
        print('scroll over')

    def esSearch(self, index_name, search=None, method='_search'):
        if search is None:
            return None
        url = self.url + '/' + index_name + '/' + method
        req = requests.post(url=url, headers=self.default_headers, verify=False, data=search.encode('utf-8'))
        if req.status_code != 200:
            print('requests error')
            return None
        return json.loads(req.content)

    def get_access_token(self, index_name_token):
        url = self.url + '/' + index_name_token + '/' + '_search'
        _headers = {'Content-Type': 'application/json;charset=UTF-8', 'Authorization': self.authorization}
        query = '''{
            "query": {
                "bool": {
                    "must": [
                        {
                            "match_all": {}
                        }
                    ],
                    "must_not": [],
                    "should": []
                }
            },
            "from": 0,
            "size": 1000,
            "sort": {
                "created_at": {
                    "order": "desc"
                }
            },
            "aggs": {}
        }'''
        res = self.request_get(url=url, headers=_headers, data=query)
        if res.status_code != 200:
            print('The index not exist, error=', res.json())
            return []
        token = res.json()
        cur_service = token['hits']['hits']
        services = []
        for i in range(len(cur_service)):
            service_token = cur_service[i]['_source']
            services.append(service_token)

        return services

    def get_access_token_service(self, index_name_token, service):
        url = self.url + '/' + index_name_token + '/' + '_search'
        _headers = {'Content-Type': 'application/json;charset=UTF-8', 'Authorization': self.authorization}
        query = '''{
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "service.keyword": "%s"
                            }
                        }
                    ]
                }
            }
        }''' % service
        res = self.request_get(url=url, headers=_headers, data=query)
        if res.status_code != 200:
            print('The index not exist, error=', res.json())
            return []
        token = res.json()
        hits = token['hits']['hits']
        for hit in hits:
            return hit.get('_source').get('access_token')
        return None

    def request_get(self, url, data=None, headers=None, params=None, verify=False, timeout=60):
        res = requests.get(url, data=data, headers=headers, params=params, verify=verify, timeout=timeout)
        return res


def create_log_dir(dest_dir):
    '''
    create a local dir object under root project dir
    :param dest_dir: the wanted dir name
    :return: local dir object
    '''
    commandline = f'mkdir -p {dest_dir}'

    if os.path.exists(dest_dir):
        return True

    try:
        exec_out_file = subprocess.Popen(commandline, shell=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
    except Exception as exp:
        print(f'Failed to create log dir for reason:{exp.__repr__()}')
        return False


def get_date(time):
    if time:
        return time.split("+")[0]
    else:
        return None


def get_time_to_first_attention(item):
    """Get the first date at which a comment or reaction was made to the issue by someone
    other than the user who created the issue
    """
    comment_dates = [str_to_datetime(comment['created_at']) for comment in item['comments_data']
                     if item['user']['login'] != comment['user']['login']]
    if comment_dates:
        return min(comment_dates)
    return None


def get_first_contribute_at(user, current_date):
    if user in gloabl_item:
        if str_to_datetime(current_date) < str_to_datetime(gloabl_item[user]):
            gloabl_item[user] = current_date
            return current_date
        else:
            return None
    else:
        gloabl_item[user] = current_date
        return current_date


def get_time_diff_days(start, end):
    ''' Number of days between two dates in UTC format  '''

    if start is None or end is None:
        return None

    if type(start) is not datetime:
        start = dateutil.parser.parse(start).replace(tzinfo=None)
    if type(end) is not datetime:
        end = dateutil.parser.parse(end).replace(tzinfo=None)

    seconds_day = float(60 * 60 * 24)
    diff_days = (end - start).total_seconds() / seconds_day
    diff_days = float('%.2f' % diff_days)

    return diff_days


def get_time_diff_seconds(start, end):
    ''' Number of days between two dates in UTC format  '''

    if start is None or end is None:
        return None

    if type(start) is not datetime:
        start = dateutil.parser.parse(start).replace(tzinfo=None)
    if type(end) is not datetime:
        end = dateutil.parser.parse(end).replace(tzinfo=None)

    diff_second = (end - start).total_seconds()

    return diff_second


def datetime_utcnow():
    """Handy function which returns the current date and time in UTC."""
    return datetime.now()


def str_to_datetime(ts):
    """Format a string to a datetime object.
    This functions supports several date formats like YYYY-MM-DD,
    MM-DD-YYYY, YY-MM-DD, YYYY-MM-DD HH:mm:SS +HH:MM, among others.
    When the timezone is not provided, UTC+0 will be set as default
    (using `dateutil.tz.tzutc` object).
    :param ts: string to convert
    :returns: a datetime object
    :raises IvalidDateError: when the given string cannot be converted
        on a valid date
    """

    def parse_datetime(ts):
        dt = dateutil.parser.parse(ts)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=dateutil.tz.tzutc())
        return dt

    if not ts:
        raise InvalidDateError(date=str(ts))

    try:
        # Try to remove additional information after
        # timezone section because it cannot be parsed,
        # like in 'Wed, 26 Oct 2005 15:20:32 -0100 (GMT+1)'
        # or in 'Thu, 14 Aug 2008 02:07:59 +0200 CEST'.
        m = re.search(r"^.+?\s+[\+\-\d]\d{4}(\s+.+)$", ts)
        if m:
            ts = ts[:m.start(1)]

        try:
            dt = parse_datetime(ts)
        except ValueError as e:
            # Try to remove the timezone, usually it causes
            # problems.
            m = re.search(r"^(.+?)\s+[\+\-\d]\d{4}.*$", ts)

            if m:
                dt = parse_datetime(m.group(1))
                print("Date %s does not have a valid timezone. "
                      "Date converted removing timezone info" % ts)
                return dt

            raise e

        try:
            # Check that the offset is between -timedelta(hours=24) and
            # timedelta(hours=24). If it is not the case, convert the
            # date to UTC and remove the timezone info.
            _ = dt.astimezone(dateutil.tz.tzutc())
        except ValueError:
            print("Date %s does not have a valid timezone; timedelta not in range. "
                  "Date converted to UTC removing timezone info" % ts)
            dt = dt.replace(tzinfo=dateutil.tz.tzutc()).astimezone(dateutil.tz.tzutc())

        return dt

    except ValueError as e:
        raise InvalidDateError(date=str(ts))


def getSingleAction(index_name, id, body, act="index"):
    action = ""
    indexData = {
        act: {"_index": index_name, "_id": id}}
    # indexData = {
    #     act: {"_index": index_name, "_type": "items", "_id": id}}
    action += json.dumps(indexData) + '\n'
    action += json.dumps(body) + '\n'
    return action


def writeDataThread(thread_func_args, max_thread_num=20):
    threads = []

    for key, values in thread_func_args.items():
        for v in values:
            if not isinstance(v, tuple):
                args = (v,)
            else:
                args = v
            t = threading.Thread(
                target=key,
                args=args)
            threads.append(t)
            t.start()

            if len(threads) % max_thread_num == 0:
                for t in threads:
                    t.join()
                print("finish threads num:", max_thread_num)
                threads = []

    for t in threads:
        t.join()


def getGenerator(response):
    data = []
    try:
        while 1:
            if isinstance(response, types.GeneratorType):
                data += json.loads(next(response).encode('utf-8'))
            else:
                data = json.loads(response)
                break
    except StopIteration:
        # print(response)
        print("...end")
    except JSONDecodeError:
        print("Gitee get JSONDecodeError, error: ", response)

    return data


def show_spend_seconds_of_this_function(func):
    '''
    :param func: the function, is noted
    :return: the total spend time of the given fucniton
    '''

    def wrapper(*args, **kw):
        thread_name = threading.current_thread().getName()
        start_time_point = time.time()
        func_value = func(*args, **kw)
        end_time_point = time.time()
        spend_seconds = end_time_point - start_time_point
        pretty_second = round(spend_seconds, 1)
        print(f'{thread_name} === Function name: {func.__name__}, Spend seconds: {pretty_second}s\n')
        return func_value

    return wrapper


def get_beijingTime():
    ''' Get beijing time from different local time zone
    :return: standardized beijing time from right now
    '''
    utc_now_time = datetime.now(tz=pytz.timezone('UTC'))
    tz = pytz.timezone('Asia/Shanghai')
    beijingTime = utc_now_time.astimezone(tz)
    return beijingTime


def convert_to_localTime(input_datetime):
    '''
    Convert the given datetime object to local time base local timezone
    :param input_datetime: a given datetime object
    :return: a local time based on local timezone
    '''

    local_tz = get_localzone()
    return input_datetime.astimezone(local_tz)

def convert_to_date_str(input_timestamp):
    """
    Convert the given timestamp object to date_str
    :param input_timestamp: a given timestamp object
    :return: date_str
    """
    ts_obj = datetime.fromtimestamp(input_timestamp)
    date_str = ts_obj.strftime('%Y-%m-%dT%H:%M:%S+08:00')
    return date_str