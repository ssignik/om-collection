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
import os
import re
import json
import requests
import time
import yaml
import subprocess

from collections import defaultdict
from collect.gitee import GiteeClient
from data.common import ESClient
from data.gitee import Gitee


class SigMaintainer(object):

    def __init__(self, config=None):
        self.config = config
        self.index_name = config.get('index_name')

        self.url = config.get('es_url')
        self.authorization = config.get('authorization')

        self.esClient = ESClient(config)
        self.gitee = Gitee(config)
        self.org = config.get("org")
        self.sigs_dir = config.get('sigs_dir')
        self.sigs_url = config.get('sigs_url')
        self.index_name_sigs = config.get('index_name_sigs')

        self.gitee_token = config.get('gitee_token')
        self.sigs_source = config.get('sigs_source')
        self.headers = {'Content-Type': 'application/json', "Authorization": config.get('authorization')}
        self.sig_repo_name = config.get('sig_repo_name')
        self.sigs_dirs_path = config.get('sigs_dirs_path')
        self.from_data = config.get("from_data")
        self.get_repo_name_without_sig = config.get("get_repo_name_without_sig")
        self.sig_mark = config.get("sig_mark")
        self.exists_ids = []
        self.sig_label_dict = None
        self.sig_label_path = config.get('sig_label_path')
        self.sig_mail_dict = {}
        self.maillist_path = config.get('maillist_path')
        self.owner_info_dict = {}
        self.email_gitee_es = config.get('email_gitee_es')
        self.email_gitee_authorization = config.get('email_gitee_authorization')
        self.email_gitee_index = config.get('email_gitee_index')
        self.platform = config.get('platform', 'gitee')

    def run(self, from_time):
        self.download_sigs()
        self.get_sig_mail()
        if self.index_name_sigs and self.sig_mark:
            self.get_all_id()
            sig_repo_dict = self.get_sig_repo_dict()
            maintainer_sigs_dict = self.get_sigs_original(sig_repo_dict)
            self.get_sigs(sig_repo_dict, maintainer_sigs_dict)

    def getSingleAction(self, index_name, id, body, act="index"):
        action = ""
        indexData = {
            act: {"_index": index_name, "_id": id}}
        action += json.dumps(indexData) + '\n'
        action += json.dumps(body) + '\n'
        return action

    def mark_removed_sigs(self, dirs, index):
        time.sleep(5)
        search = '''{
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
                        "field": "sig_name.keyword",
                        "size": 10000,
                        "order": {
                            "_key": "desc"
                        },
                        "min_doc_count": 0
                    },
                    "aggs": {}
                }
            }
        }'''
        url = self.url + '/' + index + '/_search'
        res = requests.post(url, headers=self.esClient.default_headers, verify=False, data=search)
        data = res.json()

        removed_sigs = ['sig-template', 'Template']
        for sig in data['aggregations']['2']['buckets']:
            sig_name = sig['key']
            if sig_name not in dirs:
                removed_sigs.append(sig_name)

        for s in removed_sigs:
            mark = '''{
                "script": {
                    "source":"ctx._source['is_removed']=1"
                },
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "query_string": {
                                    "analyze_wildcard": true,
                                    "query": "sig_name.keyword:%s AND !is_removed:1"
                                }
                            }
                        ]
                    }
                }
            }''' % s
            url = self.url + '/' + index + '/_update_by_query'
            requests.post(url, headers=self.esClient.default_headers, verify=False, data=mark)
            print('<%s> has been marked for removal' % s)

    def get_sig_repos_openeuler(self):
        sig_repos_dict = {}
        dirs = os.walk(self.sigs_dirs_path).__next__()[1]
        for sig in dirs:
            sig_repo_path = self.sigs_dirs_path + '/' + sig
            repo_path_dirs = os.walk(sig_repo_path).__next__()[1]
            sig_repo_list = self.get_sig_repos_by_org('openeuler', repo_path_dirs, sig_repo_path)
            sig_repo_list.extend(self.get_sig_repos_by_org('src-openeuler', repo_path_dirs, sig_repo_path))
            sig_repos_dict.update({sig: sig_repo_list})
        return sig_repos_dict

    def get_sig_repos_openubmc(self):
        sig_repos_dict = {}
        dirs = os.walk(self.sigs_dirs_path).__next__()[1]
        for sig in dirs:
            repo_path_dir = os.path.join(self.sigs_dirs_path, sig, 'repo-info.yaml')
            try:
                repo_info = yaml.load_all(open(repo_path_dir), Loader=yaml.BaseLoader).__next__()
                sig_repo_list = []
                for repo in repo_info:
                    sig_repo_list.append(self.org + '/' + repo['name'])
                sig_repos_dict.update({sig: sig_repo_list})
            except (yaml.YAMLError, IOError) as e:
                print(f"Error reading or parsing {repo_path_dir}: {e}")
        return sig_repos_dict

    @staticmethod
    def get_sig_repos_by_org(org, repo_path_dirs, sig_repo_path):
        sig_repo_list = []
        if org not in repo_path_dirs:
            return sig_repo_list
        repo_path_dir = os.path.join(sig_repo_path, org)
        for root, dirs, files in os.walk(repo_path_dir):
            for file in files:
                yaml_path = os.path.join(root, file)
                try:
                    name = yaml.load_all(open(yaml_path), Loader=yaml.BaseLoader).__next__()['name']
                    repo_name = f"{org}/{name}"
                    sig_repo_list.append(repo_name)
                except (yaml.YAMLError, IOError) as e:
                    print(f"Error reading or parsing {yaml_path}: {e}")
        return sig_repo_list

    def get_sig_repos_opengauss(self):
        sig_yaml_path = self.sigs_dir + self.sig_repo_name + '/sigs.yaml'
        data = yaml.load_all(open(sig_yaml_path), Loader=yaml.BaseLoader).__next__()['sigs']
        sig_repos_dict = {}
        for d in data:
            repos = d['repositories']
            repositories = []
            if repos is None:
                break
            for repo in repos:
                if self.get_repo_name_without_sig:
                    repositories.append(repo)
                else:
                    repositories.append(self.org + '/' + repo)
            sig_repos_dict.update({d['name']: repositories})

        return sig_repos_dict

    def get_sig_repo_dict(self):
        sig_repos_dict = {}
        if self.org == 'openeuler':
            sig_repos_dict = self.get_sig_repos_openeuler()
        elif self.org == 'opengauss':
            sig_repos_dict = self.get_sig_repos_opengauss()
        else:
            sig_repos_dict = self.get_sig_repos_openubmc()
        return sig_repos_dict

    def get_id_func(self, hit):
        for data in hit:
            self.exists_ids.append(data['_id'])

    def get_all_id(self):
        search = '''{
            "size": 10000,
            "_source": {
                "includes": [
                    "committer"
                ]
            },
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "is_sig_repo_committer:1 AND !is_removed:1"
                            }
                        }
                    ]
                }
            }
        }'''
        self.esClient.scrollSearch(self.index_name_sigs, search=search, func=self.get_id_func)

    def mark_removed_ids(self):
        for removed_id in self.exists_ids:
            mark = '''{
                            "script": {
                                "source":"ctx._source['is_removed']=1"
                            },
                            "query": {
                                "term": {
                                    "_id":"%s"
                                }
                            }
                        }''' % removed_id
            url = self.url + '/' + self.index_name_sigs + '/_update_by_query'
            requests.post(url, headers=self.esClient.default_headers, verify=False, data=mark)

    def get_readme_log(self, repo_path):
        cmdlog = 'cd %s;git log -p README.md' % repo_path
        log_popen = subprocess.Popen(cmdlog, stdout=subprocess.PIPE, shell=True)
        log = bytes.decode(log_popen.stdout.read(), encoding="utf-8", errors='ignore')
        loglist = log.split('\n')
        n = 0
        rs = []
        for index in range(len(loglist)):
            if re.search(r'^commit .*', loglist[index]):
                rs.append('\n'.join(loglist[n:index]))
                n = index
        rs.append('\n'.join(loglist[n:]))
        times = None
        for r in rs:
            if re.search(r'^commit .*', r):
                date = re.search(r'Date: (.*)\n', r).group(1)
                # time_struct = time.strptime(date[2:], '%a %b %d %H:%M:%S %Y')
                time_struct = time.strptime(date.strip()[:-6], '%a %b %d %H:%M:%S %Y')
                times = time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time_struct)
        return times

    def get_owner_log(self, repo_path):
        cmdowner = 'cd %s;git log -p OWNERS' % repo_path
        owners_popen = subprocess.Popen(cmdowner, stdout=subprocess.PIPE, shell=True)
        owners = bytes.decode(owners_popen.stdout.read(), encoding="utf-8")
        ownerslist = owners.split('\n')
        n = 0
        rs = []
        for index in range(len(ownerslist)):
            if re.search(r'^commit .*', ownerslist[index]):
                rs.append('\n'.join(ownerslist[n:index]))
                n = index
        rs.append('\n'.join(ownerslist[n:]))
        return rs

    def get_sig_info_log(self, repo_path):
        cmdlog = 'cd %s;git log -p sig-info.yaml' % repo_path
        log_popen = subprocess.Popen(cmdlog, stdout=subprocess.PIPE, shell=True)
        log = bytes.decode(log_popen.stdout.read(), encoding="utf-8", errors='ignore')
        loglist = log.split('\n')
        n = 0
        rs = []
        for index in range(len(loglist)):
            if re.search(r'^commit .*', loglist[index]):
                rs.append('\n'.join(loglist[n:index]))
                n = index
        rs.append('\n'.join(loglist[n:]))
        return rs

    def get_sig_info(self, owner_type, repos, users, dir, repo_committer_dic=None):
        repo_path = self.sigs_dirs_path + '/' + dir
        rs = self.get_sig_info_log(repo_path)
        datas = ''
        for user in users:
            times_owner = None
            times = self.get_readme_log(repo_path)
            for r in rs:
                if r == '':
                    continue
                if re.search(r'\+\s*-\s*%s_id:\s*%s' % (self.platform, user), r):
                    date = re.search(r'Date:\s*(.*)\n', r).group(1)
                    # time_struct = time.strptime(date, '%a %b %d %H:%M:%S %Y')
                    time_struct = time.strptime(date.strip()[:-6], '%a %b %d %H:%M:%S %Y')
                    times_owner = time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time_struct)
            repo_mark = True
            for repo in repos:
                committers = repo_committer_dic.get(repo, []) if repo_committer_dic else []
                if owner_type == 'committers' and user not in committers:
                    continue
                ID = self.org + '_' + dir + '_' + repo + '_' + owner_type + '_' + user
                if ID in self.exists_ids:
                    self.exists_ids.remove(ID)
                dataw = self.writecommonData(dir, repo, owner_type, user, times, times_owner, committers)
                datar = self.getSingleAction(self.index_name_sigs, ID, dataw)
                datas += datar
                repo_mark = False
            if repo_mark:
                ID = self.org + '_' + dir + '_null_' + owner_type + '_' + user
                if ID in self.exists_ids:
                    self.exists_ids.remove(ID)
                dataw = self.writecommonData(dir, None, owner_type, user, times, times_owner)
                datar = self.getSingleAction(self.index_name_sigs, ID, dataw)
                datas += datar
        return datas

    def writecommonData(self, dir, repo, owner_type, user, times, times_owner, committers=None):
        dataw = {"sig_name": dir,
                 "repo_name": repo,
                 "committer": user,
                 "user_login": user,
                 "created_at": times,
                 "committer_time": times_owner,
                 "is_sig_repo_committer": 1,
                 "owner_type": owner_type}
        if user in self.owner_info_dict:
            dataw.update(self.owner_info_dict[user])
        if committers and user in committers:
            dataw['is_repo_committer'] = 1
        userExtra = self.esClient.getUserInfo(user)
        dataw.update(userExtra)
        return dataw

    def get_repo_committer_from_yaml(self, info):
        repo_committer_dict = {}
        committers = []
        for repo in info.get('repositories'):
            try:
                for r in repo['repo']:
                    if repo.get('committers'):
                        user_login = [user[f'{self.platform}_id'] for user in repo['committers']]
                        repo_committer_dict.update({r: user_login})
                if 'committers' in repo:
                    committers.extend(repo['committers'])
            except TypeError as e:
                print("Committer has all repository permissions")
                committers = info.get('committers', [])
                user_login = [user[f'{self.platform}_id'] for user in committers]
                repo_committer_dict.update({repo: user_login})
        return committers, repo_committer_dict

    def download_sigs(self):
        path = self.sigs_dir
        url = self.sigs_url
        if not os.path.exists(path):
            os.makedirs(path)
        gitpath = path + self.sig_repo_name
        if not os.path.exists(gitpath):
            cmdclone = 'cd %s;git clone %s' % (path, url)
            os.system(cmdclone)
        else:
            cmdpull = 'cd %s;git pull' % gitpath
            os.system(cmdpull)

    def get_sigs(self, sig_repos_dict=None, maintainer_sigs_dict=None):
        dic = self.esClient.getOrgByGiteeID()
        self.esClient.giteeid_company_dict = dic[0]
        self.gitee.internalUsers = self.gitee.getItselfUsers(self.gitee.internal_users)

        dirs = os.walk(self.sigs_dirs_path).__next__()[1]

        for dir in dirs:
            try:
                repo_path = self.sigs_dirs_path + '/' + dir
                owner_file = repo_path + '/' + 'OWNERS'
                owner_logins = yaml.load_all(open(owner_file), Loader=yaml.BaseLoader).__next__()
                times = self.get_readme_log(repo_path)
                rs = self.get_owner_log(repo_path)
                datas = ''
                for key, val in owner_logins.items():
                    key = key.lower()
                    key = "committers" if key == "committer" else key
                    if key != 'committers' and key != 'maintainers':
                        continue
                    for owner in val:
                        times_owner = None
                        for r in rs:
                            if re.search(r'\+\s*-\s*%s' % owner, r):
                                date = re.search(r'Date:\s*(.*)\n', r).group(1)
                                # time_struct = time.strptime(date, '%a %b %d %H:%M:%S %Y')
                                time_struct = time.strptime(date.strip()[:-6], '%a %b %d %H:%M:%S %Y')
                                times_owner = time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time_struct)

                        repo_mark = True
                        repos = []
                        if dir in sig_repos_dict:
                            repos = sig_repos_dict.get(dir, [])
                        for repo in repos:
                            ID = self.org + '_' + dir + '_' + repo + '_' + key + '_' + str(owner)
                            if ID in self.exists_ids:
                                self.exists_ids.remove(ID)
                            dataw = self.writecommonData(dir, repo, key, owner, times, times_owner)
                            if key == "maintainers":
                                dataw.update({"maintainer_in_sigs": maintainer_sigs_dict.get(owner)})
                            datar = self.getSingleAction(self.index_name_sigs, ID, dataw)
                            datas += datar
                            repo_mark = False

                        if repo_mark:
                            ID = self.org + '_' + dir + '_null_' + key + '_' + owner
                            if ID in self.exists_ids:
                                self.exists_ids.remove(ID)
                            dataw = self.writecommonData(dir, None, key, owner, times, times_owner)
                            if key == "maintainers":
                                dataw.update({"maintainer_in_sigs": maintainer_sigs_dict.get(owner)})
                            datar = self.getSingleAction(self.index_name_sigs, ID, dataw)
                            datas += datar
                self.esClient.safe_put_bulk(datas)
                print("this sig done: %s" % dir)
            except FileNotFoundError:
                print('OWNER of %s is not exist. Using sig-info.yaml!' % dir)
                try:
                    repo_committer_dic = {}
                    sig_info = self.sigs_dirs_path + '/' + dir + '/' + 'sig-info.yaml'
                    info = yaml.load_all(open(sig_info), Loader=yaml.BaseLoader).__next__()
                    if info.get('repositories'):
                        committers, repo_committer_dic = self.get_repo_committer_from_yaml(info)
                    else:
                        committers = info.get('committers')
                    repos = sig_repos_dict.get(dir, [])
                    datas = ''
                    if 'maintainers' in info and info['maintainers']:
                        users_info = info['maintainers']
                        maintainer_users = [user[f'{self.platform}_id'] for user in users_info]
                        datas = self.get_sig_info('maintainers', repos, maintainer_users, dir)

                    if committers and len(committers) != 0:
                        committer_users = [user[f'{self.platform}_id'] for user in committers]
                        datas += self.get_sig_info('committers', repos, committer_users, dir, repo_committer_dic)
                    self.esClient.safe_put_bulk(datas)
                    print("this sig done: %s" % dir)
                except FileNotFoundError:
                    print('sig-info.yaml of %s is not exist. ' % dir)
            except Exception as e:
                print("this sig error: %s" % dir)

        self.mark_removed_sigs(dirs=dirs, index=self.index_name_sigs)
        self.mark_removed_ids()

    def get_sigs_original(self, sig_repos_dict):
        dirs = os.walk(self.sigs_dirs_path).__next__()[1]
        if self.org == 'opengauss':
            self.sig_label_dict = self.get_gauss_sig_label()

        actions = ''
        dict_comb = defaultdict(dict)
        for dir in dirs:
            repo_path = self.sigs_dirs_path + '/' + dir
            times = self.get_readme_log(repo_path)
            # get repos
            repositories = []
            if dir in sig_repos_dict:
                repositories = sig_repos_dict.get(dir, [])
            # sig actions
            action = {
                "sig_name": dir,
                "repos": repositories,
                "is_sig_original": 1,
                "created_at": times
            }
            if self.org == 'opengauss':
                action.update({"tag_sig_name": self.sig_label_dict.get(dir)})
            maintainers = []
            try:
                # get maintainers
                owner_file = self.sigs_dirs_path + '/' + dir + '/' + 'OWNERS'
                owners = yaml.load_all(open(owner_file), Loader=yaml.BaseLoader).__next__()
                try:
                    maintainers = owners.get('maintainers')
                    if 'meeting_agenda' not in owners:
                        action.update({'meeting_agenda': owners.get("meeting_agenda")})
                    if 'discuss_url' not in owners:
                        action.update({'discuss_url': owners.get("discuss_url")})
                    action.update({'maintainers': maintainers})
                    action.update({'maintainer_info': self.attach_user_info(maintainers)})
                    committers = owners.get('committers')
                    action.update({'committers': committers})
                    action.update({'committer_info': self.attach_user_info(committers)})
                    action.update({'mailing_list': self.sig_mail_dict.get(dir, 'dev@openeuler.org')})
                except KeyError as e:
                    print('KeyError of %s is null.' % dir)
            except FileNotFoundError:
                print('owner file of %s is not exist. using sig-info.yaml.' % dir)
                try:
                    sig_info = self.sigs_dirs_path + '/' + dir + '/' + 'sig-info.yaml'
                    info = yaml.load_all(open(sig_info), Loader=yaml.BaseLoader).__next__()
                    for key, value in info.items():
                        action[key] = value
                    if 'description' in info and info['description'] is not None:
                        action.update({'description': info['description']})
                    if 'mentors' in info and info['mentors'] is not None:
                        action.update({'mentors': info['mentors']})
                    if 'meeting_agenda' not in info:
                        action.update({'meeting_agenda': info.get("meeting_agenda")})
                    if 'discuss_url' not in info:
                        action.update({'discuss_url': info.get("discuss_url")})
                    mailing_list = self.get_mailing_list(dir, info)
                    action.update({'mailing_list': mailing_list})

                    if 'maintainers' in info and info['maintainers'] is not None:
                        maintainer_list = info['maintainers']
                        self.get_owner_info(maintainer_list)
                        action.update({'maintainer_info': self.attach_user_info(maintainer_list)})
                        maintainers = [user[f'{self.platform}_id'] for user in info['maintainers']]
                        action.update({'maintainers': maintainers})
                    if info.get('committers'):
                        self.get_owner_info(info['committers'])
                        action.update({'committer_info': self.attach_user_info(info['committers'])})
                        committers = [user[f'{self.platform}_id'] for user in info['committers']]
                        action.update({'committers': committers})
                    if info.get('repositories'):
                        committer_list = self.get_repo_committer_from_yaml(info)[0]
                        self.get_owner_info(committer_list)
                        action.update({'committer_info': self.attach_user_info(committer_list)})
                        committers = [user[f'{self.platform}_id'] for user in committer_list]
                        action.update({'committers': committers})
                except FileNotFoundError:
                    print('sig-info.yaml %s is not exist.' % dir)

            # get maintainer sigs dict
            dt = defaultdict(dict)
            for maintainer in maintainers:
                dt.update({maintainer: [dir]})
            combined_keys = dict_comb.keys() | dt.keys()
            dict_comb = {key: dict_comb.get(key, []) + dt.get(key, []) for key in combined_keys}

            indexData = {"index": {"_index": self.index_name_sigs, "_id": dir}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(action) + '\n'
        self.esClient.safe_put_bulk(actions)
        return dict_comb

    def get_user_info(self, user):
        if user is None:
            return
        client = GiteeClient(self.org, None, self.gitee_token)
        res = client.gitee_user(user)
        if res.status_code != 200:
            return
        user = res.json()
        return user.get('avatar_url')

    def attach_user_info(self, users):
        if users is None or len(users) == 0:
            return
        user_list = []
        for user in users:
            try:
                login_id = user.get(f'{self.platform}_id')
                user_dict = user
                user_dict['avatar_url'] = self.owner_info_dict.get(login_id, {}).get('avatar_url')
            except AttributeError:
                user_dict = {f'{self.platform}_id': user}
            user_list.append(user_dict)
        return user_list

    def get_gauss_sig_label(self):
        if self.sig_label_path is None:
            return {}
        data = yaml.load_all(open(self.sig_label_path), Loader=yaml.BaseLoader).__next__().get('sigs')
        sig_label_dict = {}
        for d in data:
            name = d.get('name')
            label = d.get('sig_label')
            sig_label_dict.update({name: label})
        return sig_label_dict

    def get_sig_mail(self):
        if self.org == 'openeuler':
            _headers = {
                'Content-Type': 'application/json',
            }
            res = self.esClient.request_get(url=self.maillist_path, headers=_headers, timeout=60)
            if res.status_code != 200:
                return
            sig_list = yaml.safe_load(res.text)
            for info in sig_list:
                sig = info.get('group_name')
                maillist = info.get('maillist')
                self.sig_mail_dict.update({sig: maillist})
        elif self.org == 'opengauss':
            try:
                res = yaml.load_all(open(self.maillist_path), Loader=yaml.BaseLoader).__next__()
                for key, val in res.items():
                    self.sig_mail_dict.update({key: val})
            except FileNotFoundError:
                print('maillist_path missing.')

    def get_mailing_list(self, sig, info):
        mailing_list = 'dev@openeuler.org'
        if 'mailing_list' in info and info['mailing_list'] is not None:
            if '@' not in info['mailing_list'] or info['mailing_list'] == 'dev@openeuler.org':
                mailing_list = self.sig_mail_dict.get(sig, mailing_list)
            else:
                mailing_list = info['mailing_list']
        else:
            mailing_list = self.sig_mail_dict.get(sig, mailing_list)
        return mailing_list

    def get_owner_info(self, owners):
        for owner in owners:
            login_id = owner.get(f'{self.platform}_id')
            if not login_id:
                continue
            if login_id not in self.owner_info_dict:
                email = self.get_email_by_gitee_id(login_id)
                if owner.get('email') and owner.get('email', 'na').lower() != 'na':
                    email = owner.get('email')
                owner_info = {
                    'organization': owner.get('organization', 'na'),
                    'email': email,
                    'name': owner.get('name'),
                    'avatar_url': self.get_user_info(login_id)
                }
                self.owner_info_dict[login_id] = owner_info
            else:
                if owner.get('email', 'na').lower() != 'na':
                    self.owner_info_dict[login_id].update({'email': owner.get('email')})
                if owner.get('organization', 'na').lower() != 'na':
                    self.owner_info_dict[login_id].update({'organization': owner.get('organization')})

    def get_email_by_gitee_id(self, login_id):
        search = '''{
            "size": 10,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "query_string": {
                                "analyze_wildcard": true,
                                "query": "gitee_id.keyword:%s"
                            }
                        }
                    ]
                }
            },
            "sort": [
                {
                    "created_at": {
                        "order": "desc"
                    }
                }
            ]
        }''' % login_id
        headers = {
                'Content-Type': 'application/json',
                'Authorization': self.email_gitee_authorization
            }
        resp = self.esClient.request_get(
            self.esClient.getSearchUrl(url=self.email_gitee_es, index_name=self.email_gitee_index),
            data=search,
            headers=headers)
        email = 'NA'
        if resp.status_code == 200:
            hits = resp.json().get('hits').get('hits')
            for hit in hits:
                email = hit.get('_source').get('email')
                break

        return email
