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
import signal
from collections import defaultdict

import yaml
import json
import requests
import logging

import re
import types
import threading

import dateutil.parser
import dateutil.rrule
import dateutil.tz

import time
import datetime

from json import JSONDecodeError
from data import common
from data.common import ESClient
from data.gitee_pr_version import GiteePrVersion
from collect.gitee import GiteeClient

logger = logging.getLogger(__name__)

ISSUE_TYPE = 'issue'
PULL_TYPE = 'pull_request'
COMMENT_TYPE = 'comment'
ISSUE_COMMENT_TYPE = 'issue_comment'
REVIEW_COMMENT_TYPE = 'review_comment'
REPOSITORY_TYPE = 'repository'
COMMIT_TYPE = 'commit'


class Gitee(object):

    def __init__(self, config=None):
        self.config = config
        self.orgs = self.getOrgs(config.get('orgs'))
        self.index_name = config.get('index_name')
        self.gitee_token = config.get('gitee_token')
        self.skip_user = config.get('skip_user', "").split(',')
        self.esClient = ESClient(config)
        self.is_gitee_enterprise = config.get('is_gitee_enterprise')
        self.filters = config.get('gitee_repo_filter')
        self.is_update_repo_author = config.get('is_update_repo_author')
        self.is_set_itself_author = config.get('is_set_itself_author')
        self.is_set_pr_issue_repo_fork = config.get('is_set_pr_issue_repo_fork')
        self.is_set_pr = config.get('is_set_pr')
        self.is_set_repo = config.get('is_set_repo')
        self.is_set_fork = config.get('is_set_fork')
        self.is_set_issue = config.get('is_set_issue')
        self.is_set_first_contribute = config.get('is_set_first_contribute')
        self.is_set_star_watch = config.get('is_set_star_watch')
        self.is_set_sigs_star = config.get('is_set_sigs_star')
        self.internal_users = config.get('internal_users', 'users')
        self.collect_from_time = config.get('collect_from_time')
        self.is_set_collect = config.get('is_set_collect')
        self.yaml_url = config.get('yaml_url')
        self.yaml_path = config.get('yaml_path')
        # self.maintainer_index = config.get('maintain_index')
        self.sig_index = config.get('sig_index')
        self.versiontimemapping = config.get('versiontimemapping')
        self.internal_company_name = config.get('internal_company_name', 'internal_company')
        self.highest_priority_tag_company = config.get('highest_priority_tag_company', 'cla')
        self.internalUsers = []
        self.all_user = []
        self.all_user_info = []
        self.companyinfos = []
        self.enterpriseUsers = []
        self.giteeid_company_dict_last = {}
        self.index_name_all = None
        self.robot_user_logins = str(config.get('robot_user_login', 'I-am-a-robot')).split(',')
        self.blacklist_user = str(config.get('blacklist_user', '')).split(',')
        self.once_update_num_of_pr = int(config.get('once_update_num_of_pr', 200))
        if 'index_name_all' in config:
            self.index_name_all = config.get('index_name_all').split(',')
        self.repo_spec = config.get('repo_spec_mapping')
        self.tag_repo_sigs_history = config.get('tag_repo_sigs_history', 'false')
        self.is_update_removed_data = config.get('is_update_removed_data', 'false')
        self.thread_pool_num = int(config.get('thread_pool_num', 20))
        self.thread_max_num = threading.Semaphore(self.thread_pool_num)
        self.repo_sigs_dict = {}
        self.last_repo_sig = {}
        self.invalid_pr_title = config.get('invalid_pr_title')
        self.command = None
        if config.get('command_list'):
            self.command = config.get('command_list').split(',')
        self.is_collect_all = config.get('is_collect_all')
        self.multi_threading = config.get('multi_threading')
        self.company_location_index = config.get('company_location_index')
        self.set_repo_issue = config.get('set_repo_issue', 'false')
        self.set_repo_pr = config.get('set_repo_pr', 'false')
        self.set_repos = config.get('set_repos')

    def run(self, from_time):
        print("Collect gitee data: staring")
        repo_sigs_dict = self.esClient.getRepoSigs()
        self.repo_sigs_dict = self.get_dict_key_lower(repo_sigs_dict)
        self.getGiteeId2Company()

        self.getEnterpriseUser()
        startTime = time.time()
        self.internalUsers = self.getItselfUsers(self.internal_users)

        # refresh repo`s sigs history
        if self.tag_repo_sigs_history == 'true':
            self.tagRepoSigsHistory()

        if self.is_set_itself_author == 'true':
            self.tagUsers(tag_user_company=self.internal_company_name)
            # self.tagUsers()
            # self.tagHistoryUsers()
        else:
            if self.esClient.is_update_tag_company == 'true':
                self.tagHistoryUsers()
            if self.is_set_pr_issue_repo_fork == 'true':
                # self.writeData(self.writeContributeForSingleRepo, from_time)
                self.writeData(self.writePullSingleRepo, from_time)
                self.writeData(self.writeIssueSingleRepo, from_time)
                self.writeData(self.writeRepoSingleRepo, from_time)
                self.writeData(self.writeForkSingleRepo, from_time)
            if self.is_set_issue == 'true':
                self.writeData(self.writeIssueSingleRepo, from_time)
            if self.is_set_pr == 'true':
                self.writeData(self.writePullSingleRepo, from_time)
            if self.is_set_repo == 'true':
                self.writeData(self.writeRepoSingleRepo, from_time)
            if self.is_set_fork == 'true':
                self.writeData(self.writeForkSingleRepo, from_time)
            if self.set_repo_issue == 'true' and self.set_repos:
                self.writeDataRepos(self.set_repos, self.writeIssueSingleRepo, from_time)
            if self.set_repo_pr == 'true' and self.set_repos:
                self.writeDataRepos(self.set_repos, self.writePullSingleRepo, from_time)

            self.externalUpdateRepo()
            if self.is_set_first_contribute == 'true':
                self.updateIsFirstCountributeItem()
            if self.is_set_collect == 'true':
                self.collectTotal(self.collect_from_time)

            if self.is_set_star_watch == 'true':
                self.writeData(self.writeSWForSingleRepo, from_time)
            if self.is_set_sigs_star == 'true':
                self.getSartUsersList()

            change_repo_sig_dic = self.get_change_repo_sig_dict(repo_sigs_dict)
            self.esClient.tagRepoSigChanged(change_repo_sig_dic)
        endTime = time.time()
        spent_time = time.strftime("%H:%M:%S",
                                   time.gmtime(endTime - startTime))
        print("Collect all gitee data finished after %s" % spent_time)

    def tagRepoSigsHistory(self):
        data = self.esClient.getAllGiteeRepo()
        for d in data['aggregations']['repos']['buckets']:
            gitee_repo = d['key']
            repo = str(gitee_repo).replace("https://gitee.com/", "")

            sig_names = ['No-SIG']
            if repo.lower() in self.repo_sigs_dict:
                sig_names = self.repo_sigs_dict.get(repo.lower)

            if 'opengauss' in self.orgs:
                sig_names = self.get_repo_sig('opengauss', repo)

            query = """{
  "script": {
    "source": "ctx._source['sig_names']=%s"
  },
  "query": {
    "term": {
      "gitee_repo.keyword": "%s"
    }
  }
}""" % (sig_names, gitee_repo)
            self.esClient.updateByQuery(query=query)
            print('***** %s: %s *****' % (sig_names, gitee_repo))

        sig_names = ['No-SIG']
        queryNoRepo = """{
  "script": {
    "source": "ctx._source['sig_names']=%s"
  },
  "query": {
    "bool": {
      "must_not": [
        {
          "exists": {
            "field": "sig_names"
          }
        }
      ]
    }
  }
}""" % sig_names
        self.esClient.updateByQuery(query=queryNoRepo)
        print('***** No Repo No Sig *****')

    def get_change_repo_sig_dict(self, repo_sigs_dict):
        change_repo_sig_dic = {}
        self.last_repo_sig = self.esClient.getLastRepoSigs()
        for repo in self.last_repo_sig:
            if self.last_repo_sig.get(repo) and repo_sigs_dict.get(repo) != self.last_repo_sig.get(repo):
                change_repo_sig_dic[repo] = repo_sigs_dict.get(repo, ['No-SIG'])
        return change_repo_sig_dic

    def getGiteeId2Company(self):
        self.giteeid_company_dict_last = self.esClient.giteeid_company_dict
        dic = self.esClient.getOrgByGiteeID()
        self.esClient.giteeid_company_dict = dic[0]
        self.esClient.giteeid_company_change_dict = dic[1]

    def writeDataRepos(self, repos, func, from_time):
        repo_list = repos.split(',')
        for item in repo_list:
            try:
                owner, repo = item.split('/')
                repo = {
                    'path': repo,
                    'public': True
                }
                func(owner, repo, from_time)
            except:
                print('writeDataRepos error: ', item)

    def writeData(self, func, from_time):
        if self.multi_threading != 'true':
            for org in self.orgs:
                repos = self.get_repos(org)
                reposName = []
                for r in repos:
                    reposName.append(r['full_name'])
                    func(org, r, from_time)
        else:
            threads = []
            for org in self.orgs:
                repos = self.get_repos(org)
                reposName = []
                for r in repos:
                    reposName.append(r['full_name'])
                    # func(org, r, from_time)
                    with self.thread_max_num:
                        t = threading.Thread(
                            target=func,
                            args=(org, r, from_time))
                    threads.append(t)
                    t.start()

                    if len(threads) % self.thread_pool_num == 0:
                        for t in threads:
                            t.join()
                        threads = []
                # if reposName is not None and len(reposName) > 0:
                #     self.updateRemovedData(reposName, 'repo', [{
                #         "name": "is_gitee_repo",
                #         "value": 1,
                #     }])
                for t in threads:
                    t.join()
                threads = []

    def externalUpdateRepo(self):
        if self.is_update_repo_author == 'true':
            self.updateCreatedRepoAuthor()

    def getOrgs(self, orgsStr):
        orgs = []
        if orgsStr:
            orgs = orgsStr.split(",")
            print(orgs)
        else:
            print("The 'orgs' field must be set")
        return orgs

    def writeContributeForSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        is_public = repo['public']
        sig_names = self.get_repo_sig(org, repo_name)

        print('*****writeContributeForSingleRepo start: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        print('*****writeContributeForSingleRepo start, there are', threading.activeCount(), 'threads running')
        self.writeRepoData(org, repo_name, from_time, sig_names)
        self.writePullData(org, repo_name, is_public, from_time, self.once_update_num_of_pr, sig_names)
        self.writeIssueData(org, repo_name, is_public, from_time, sig_names)
        self.writeForks(org, repo_name, from_time, sig_names)
        print('*****writeContributeForSingleRepo end: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        print('*****writeContributeForSingleRepo end, there are', threading.activeCount(), 'threads running')

    def writeForkSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        is_public = repo['public']
        sig_names = self.get_repo_sig(org, repo_name)

        print('*****writeForkSingleRepo start: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        self.writeForks(org, repo_name, from_time, sig_names)
        print('*****writeForkSingleRepo end: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))

    def writeRepoSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        is_public = repo['public']
        sig_names = self.get_repo_sig(org, repo_name)

        print('*****writeRepoData start: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        self.writeRepoData(org, repo_name, from_time, sig_names)
        print('*****writeRepoData end: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))

    def writePullSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        is_public = repo['public']
        sig_names = self.get_repo_sig(org, repo_name)

        print('*****writePullSingleRepo start: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        self.writePullData(org, repo_name, is_public, from_time, self.once_update_num_of_pr, sig_names)
        print('*****writePullSingleRepo end: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))

    def writeIssueSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        is_public = repo['public']
        sig_names = self.get_repo_sig(org, repo_name)

        print('*****writeIssueSingleRepo start: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        print('*****writeIssueSingleRepo start, there are', threading.activeCount(), 'threads running')
        self.writeIssueData(org, repo_name, is_public, from_time, sig_names)
        print('*****writeIssueSingleRepo end: repo_name(%s), org(%s), thread num(%s) *****' % (repo_name, org, threading.currentThread().getName()))
        print('*****writeIssueSingleRepo end, there are', threading.activeCount(), 'threads running')

    def writeSWForSingleRepo(self, org, repo, from_time=None):
        repo_name = repo['path']
        sig_names = self.get_repo_sig(org, repo_name)

        self.writeStars(org, repo_name, sig_names)
        self.writeWatchs(org, repo_name, sig_names)

    def checkIsCollectRepo(self, path, is_public):
        filters = self.filters.split(',')
        for f in filters:
            if f in path:
                return False

            if not is_public:
                return False
        return True

    def get_repos(self, org):
        client = GiteeClient(org, None, self.gitee_token)
        print(self.is_gitee_enterprise)
        if self.is_gitee_enterprise == "true":
            org_data = self.getGenerator(client.enterprises())
        else:
            org_data = self.getGenerator(client.org())

        if self.filters is None:
            repos = []
            for repo in org_data:
                if repo['namespace']['path'] == org:
                    repos.append(repo)
            return repos

        repos = []
        for repo in org_data:
            path = repo['path']
            if self.checkIsCollectRepo(path, repo['public']):
                print(repo['path'])
                repos.append(repo)

        return repos

    def updateRemovedForks(self, gitee_repo, forks):
        matchs = [{
            "name": "is_gitee_fork",
            "value": 1,
        },
            {
                "name": "gitee_repo.keyword",
                "value": gitee_repo,
            }
        ]
        data = self.esClient.getItemsByMatchs(matchs)

        fork_num = data['hits']['total']['value']
        original_forks = data['hits']['hits']
        print("%s original fork num is (%d), The current fork num is (%d)" % (gitee_repo, fork_num, len(forks)))
        if fork_num == len(forks):
            return
        for fork in original_forks:
            if fork['_source']['fork_id'] not in forks:
                print("[update] set fork(%s) is_removed to 1" % fork['_source']['fork_id'])
                self.esClient.updateToRemoved(fork['_id'])

    def updateRemovedData(self, newdata, type, matches, matchs_not=None):
        original_ids = []
        if self.is_update_removed_data != "true":
            return original_ids
        # 获取gitee中指定仓库的所有issue
        '''matches = [{
            "name": "is_gitee_issue",
            "value": 1,
        },
            {
                "name": "gitee_repo.keyword",
                "value": gitee_repo,
            }
        ]'''
        if newdata is None or not isinstance(newdata, list):
            return original_ids
        data = self.esClient.getItemsByMatchs(matches, size=10000, matchs_not=matchs_not)
        newdataids = []
        data_num = data['hits']['total']['value']
        original_datas = data['hits']['hits']
        if type == 'repo' or type == 'fork':
            print("%s original %s num is (%d), The current %s num is (%d)" % (
                type, type, data_num, type, len(data)))
            newdataids = newdata
        else:
            print("%s original %s num is (%d), The current issue num is (%d)" % (
                matches[1]['value'], type, data_num, len(data)))
            for d in newdata:
                newdataids.append(d['id'])
        if data_num == len(newdata):
            return original_ids

        for ordata in original_datas:
            if type == 'issue':
                if ordata['_source']['issue_id'] not in newdataids:
                    print("[update] set issue(%s) is_removed to 1" % ordata['_source']['issue_id'])
                    self.esClient.updateToRemoved(ordata['_id'])
            elif type == "pr":
                if ordata['_source']['pull_id'] not in newdataids:
                    print("[update] set pull(%s) is_removed to 1" % ordata['_source']['pull_id'])
                    self.esClient.updateToRemoved(ordata['_id'])
            elif type == "star":
                starid = int(ordata['_source']['star_id'].split('star')[1])
                original_ids.append(starid)
                if starid not in newdataids:
                    print("[update] set star(%s) is_removed to 1" % ordata['_source']['star_id'])
                    self.esClient.updateToRemoved(ordata['_id'])
            elif type == "fork":
                forkid = ordata['_source']['fork_id']
                original_ids.append(forkid)
                if forkid not in newdataids:
                    print("[update] set fork(%s) is_removed to 1" % forkid)
                    self.esClient.updateToRemoved(ordata['_id'])
            elif type == "watch":
                watchid = ordata['_source']['watch_id'].split('watch')[1]
                original_ids.append(watchid)
                if watchid not in newdataids:
                    print("[update] set watch(%s) is_removed to 1" % ordata['_source']['watch_id'])
                    self.esClient.updateToRemoved(ordata['_id'])
            elif type == "repo":
                if ordata['_source']['repository'] not in newdataids:
                    print("[update] set repository(%s) is_removed to 1" % ordata['_source']['repository'])
                    self.esClient.updateToRemoved(ordata['_id'])
        return original_ids

    def writeForks(self, owner, repo, from_date, sig_names=None):
        startTime = datetime.datetime.now()

        client = GiteeClient(owner, repo, self.gitee_token)
        fork_data = self.getGenerator(client.forks())
        actions = ""

        fork_ids = []
        for fork in fork_data:
            action = {
                "sig_names": sig_names,
                "fork_id": fork["id"],
                "created_at": fork["created_at"],
                "updated_at": fork["updated_at"],
                "author_name": fork['owner']['name'],
                "user_id": fork['owner']['id'],
                "user_login": fork['owner']['login'],
                "repository": fork["full_name"],
                "org_name": owner,
                "gitee_repo": "https://gitee.com/" + owner + "/" + repo,
                "fork_gitee_repo": re.sub('.git$', '', fork['html_url']),
                "is_gitee_fork": 1,
            }
            userExtra = self.esClient.getUserInfo(action['user_login'], fork["created_at"])
            action.update(userExtra)

            indexData = {
                "index": {"_index": self.index_name, "_id": "fork_" + str(fork['id'])}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(action) + '\n'
            fork_ids.append(fork["id"])

        self.esClient.safe_put_bulk(actions)
        self.updateRemovedData(fork_ids, 'fork', [{
            "name": "is_gitee_fork",
            "value": 1,
        },
            {
                "name": "gitee_repo.keyword",
                "value": "https://gitee.com/" + owner + "/" + repo,
            }])

        endTime = datetime.datetime.now()
        print("Collect repo(%s) fork request data finished, spend %s seconds"
              % (owner + "/" + repo, (endTime - startTime).total_seconds()))

    def writeStars(self, owner, repo, sig_names=None):
        client = GiteeClient(owner, repo, self.gitee_token)
        star_data = self.getGenerator(client.stars())
        actions = ""
        original_ids = self.updateRemovedData(star_data, 'star', [{
            "name": "is_gitee_star",
            "value": 1,
        },
            {
                "name": "gitee_repo.keyword",
                "value": "https://gitee.com/" + owner + "/" + repo,
            }], matchs_not=[{"name": "is_removed", "value": "1"}])
        for star in star_data:
            if len(original_ids) != 0 and star['id'] in original_ids:
                continue
            star_id = owner + "/" + repo + "_" + "star" + str(star['id'])

            from_registerd_to_star = None
            user_details = self.getGenerator(client.user(star['login']))
            if user_details:
                from_registerd_to_star = ((datetime.datetime.strptime(star["star_at"], '%Y-%m-%dT%H:%M:%S+08:00')
                                           - datetime.datetime.strptime(user_details["created_at"],
                                                  '%Y-%m-%dT%H:%M:%S+08:00')).total_seconds())
            action = {
                "sig_names": sig_names,
                "user_id": star["id"],
                "star_id": star_id,
                "created_at": star["star_at"],
                "updated_at": common.datetime_utcnow().strftime('%Y-%m-%d'),
                "user_login": star['login'],
                "author_name": star['name'],
                "gitee_repo": "https://gitee.com/" + owner + "/" + repo,
                "org_name": owner,
                "is_gitee_star": 1,
                "user_created_at": user_details["created_at"] if user_details else None,
                "from_registerd_to_star": from_registerd_to_star
            }
            userExtra = self.esClient.getUserInfo(action['user_login'], star["star_at"])
            action.update(userExtra)
            indexData = {
                "index": {"_index": self.index_name, "_id": star_id}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(action) + '\n'
        self.esClient.safe_put_bulk(actions)

    def writeWatchs(self, owner, repo, sig_names=None):
        client = GiteeClient(owner, repo, self.gitee_token)

        watch_data = self.getGenerator(client.watchs())
        original_ids = self.updateRemovedData(watch_data, 'watch', [{
            "name": "is_gitee_watch",
            "value": 1,
        },
            {
                "name": "gitee_repo.keyword",
                "value": "https://gitee.com/" + owner + "/" + repo,
            }], matchs_not=[{"name": "is_removed", "value": "1"}])
        actions = ""
        for watch in watch_data:
            watch_id = owner + "/" + repo + "_" + "watch" + str(watch['id'])
            if len(original_ids) != 0 and watch['id'] in original_ids:
                continue
            action = {
                "sig_names": sig_names,
                "user_id": watch["id"],
                "watch_id": watch_id,
                "updated_at": common.datetime_utcnow().strftime('%Y-%m-%d'),
                "created_at": watch["watch_at"],
                "user_login": watch['login'],
                "author_name": watch['name'],
                "gitee_repo": "https://gitee.com/" + owner + "/" + repo,
                "org_name": owner,
                "is_gitee_watch": 1,
            }
            userExtra = self.esClient.getUserInfo(action['user_login'], watch["watch_at"])
            action.update(userExtra)

            indexData = {
                "index": {"_index": self.index_name, "_id": watch_id}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(action) + '\n'

        self.esClient.safe_put_bulk(actions)

    def writeRepoData(self, owner, repo, from_date=None, sig_names=None):
        client = GiteeClient(owner, repo, self.gitee_token)
        repo_data = self.getGenerator(client.repo())
        if len(repo_data) == 0 or 'created_at' not in repo_data:
            print("The repo info not exist. repo", repo)
            return
        print("*** start parse repo info ", repo)
        actions = ""
        repo_detail = {
            "created_at": repo_data["created_at"],
            "updated_at": repo_data["updated_at"],
            "repository_forks_count": int(repo_data["forks_count"]),
            "repository_stargazers_count": int(repo_data["stargazers_count"]),
            "repository_watchers_count": int(repo_data["watchers_count"]),
            "org_name": repo_data['namespace']['path'],
            "author_name": repo_data['owner']['name'],
            "owner_name": repo_data['owner']['name'],
            "owner_login": repo_data['owner']['login'],
            "user_id": repo_data['owner']['id'],
            "user_login": repo_data['owner']['login'],
            "repository": repo_data["full_name"],
            "public": repo_data["public"],
            "private": repo_data["private"],
            "gitee_repo": re.sub('.git$', '', repo_data['html_url']),
            "is_gitee_repo": 1,
        }
        userExtra = self.esClient.getUserInfo(repo_data['owner']['login'], repo_data["created_at"])
        repo_detail.update(userExtra)

        maintainerdata = self.esClient.getRepoMaintainer(self.sig_index, repo_data["full_name"])
        # maintainerdata = self.esClient.getRepoMaintainer(self.maintainer_index, repo_data["full_name"])
        repo_detail.update(maintainerdata)
        sigcount = self.esClient.getRepoSigCount(self.sig_index, repo_data["full_name"])
        repo_detail.update(sigcount)
        signames = self.esClient.getRepoSigNames(self.sig_index, repo_data['full_name'])
        repo_detail['signames'] = signames
        repo_detail['sig_names'] = sig_names
        branches = self.getGenerator(client.getSingleReopBranch())
        brinfo = self.getbranchinfo(branches, client, owner, repo, repo_data['path'], self.versiontimemapping)
        branchName = ''
        for br in brinfo:
            branchName += br['brname'] + ','
        branchName = branchName[0:len(branchName) - 1]
        repo_detail['branchName'] = branchName
        repo_detail['branch_detail'] = brinfo
        indexData = {
            "index": {"_index": self.index_name,
                      "_id": "gitee_repo_" + re.sub('.git$', '', repo_data['html_url'])}}
        actions += json.dumps(indexData) + '\n'
        actions += json.dumps(repo_detail) + '\n'
        print("*** start write repo info to ES ***", repo)
        self.esClient.safe_put_bulk(actions)
        print("*** end write repo info to ES ***", repo)

    def transVar2Data(self, var, spec):
        if var == 'description':
            des = re.compile('%description\s{0,1}\n(.+?)\n{2,}', re.DOTALL).search(spec.__getattribute__('source'))
            if des is None:
                desc_temp = re.compile(r'%description\s%{(.*)}', re.DOTALL).search(spec.__getattribute__('source'))
                if desc_temp is None:
                    return ""
                desc = desc_temp.groups()[0]
                desc = desc.split('}')[0]
                re_temp = re.compile(r'%s\s\\\n(.+?)\n{2,}' % desc, re.DOTALL).search(spec.__getattribute__('source'))
                if re_temp is None:
                    return ""
                description = re_temp.groups()
            else:
                description = des.groups()

            dre = description
            for de in description:
                if de.__contains__('%{') and de.__contains__('}'):
                    self.findVar(de, spec)
                    dre = strsss

            return dre
        data = spec.__getattribute__(var)
        resdata = ''
        if str(data).__contains__('%{') and str(data).__contains__('}'):
            self.findVar(data, spec)
            resdata = strsss
        else:
            resdata += data
        if resdata.endswith('.') or resdata.endswith("}"):
            resdata = resdata[0:len(resdata) - 1]
        return resdata

    # Multi-layer variable
    def findVar(self, versionStr, spec):
        global strsss
        allVar = re.findall(r'%{(.*?)}', versionStr)
        if len(allVar) == 0:
            strsss = versionStr
            return strsss
        for var in allVar:
            try:
                value = spec.macros[var]
            except:
                if str(var).replace("patch", "") not in spec.macros:
                    value = ""
                else:
                    value = spec.macros[str(var).replace("patch", "")]
            versionStr = str(versionStr).replace('%{' + var + '}', value)
        self.findVar(versionStr, spec)

    def getbranchinfo(self, branches, client, owner, repo, repopath, versiontimemapping_index):
        result = []
        version = None
        print("start getbranchinfo repo: ", repo)

        for br in branches:
            brresult = {}
            print('start getbranchinfo br reop:%s branch:%s ' % (repopath, br['name']))
            try:
                brresult["brname"] = br['name']
                spec = client.getspecFile(owner, repo, br['name'])
                print('client getspecFile br reop:%s branch:%s success, spec(%s)' % (repopath, br['name'], spec))
                if spec is not None:
                    package_name = self.transVar2Data('name', spec)
                    versionstr = self.transVar2Data('version', spec)
                    summary = self.transVar2Data('summary', spec)
                    description = self.transVar2Data('description', spec)
                    brresult['package_name'] = package_name
                    brresult['summary'] = summary
                    brresult['description'] = description
                    brresult['version'] = versionstr
                    print("getbranchinfo success, repo(%s) br(%s): " % (repopath, br['name']))
            except Exception as e:
                print('reop:%s branch:%s has No version' % (repopath, br['name']))
                result.append(brresult)
            if version and self.versiontimemapping:
                times = self.esClient.geTimeofVersion(version, repopath, versiontimemapping_index)
                interval = 0
                if times is not None:
                    interval = datetime.datetime.now() - datetime.datetime.strptime(times, '%Y-%m-%d %H:%M:%S')
                    print("releasetime:" + str(times))
                else:
                    times = ""
                    # 版本发布到目前时间
                brresult['releasetime2now'] = 0 if interval == 0 else interval.days
                # 版本号

                # 版本发布时间
                brresult['releasetime'] = times
                print('reop:%s branch:%s has No version' % (repopath, br['name']))
            print('end getbranchinfo br reop:%s branch:%s ' % (repopath, br['name']))
            result.append(brresult)
        print("end getbranchinfo repo: ", repo)
        return result

    def getFromDate(self, from_date, filters):
        if self.is_collect_all == 'true' and from_date:
            from_date = common.str_to_datetime(from_date)
        else:
            from_date = self.esClient.get_from_date(filters)
            if from_date is None:
                from_date = common.str_to_datetime(self.config.get('from_data'))
        return from_date

    def writePullData(self, owner, repo, public, from_date=None, once_update_num_of_pr=200, sig_names=None):
        startTime = datetime.datetime.now()
        from_date = self.getFromDate(from_date, [
            {"name": "is_gitee_pull_request", "value": 1},
            {"name": "gitee_repo.keyword", "value": "https://gitee.com/" + owner + "/" + repo}])
        print("Start collect %s pull data from %s" % (repo, from_date))

        client = GiteeClient(owner, repo, self.gitee_token)

        if public:
            client = GiteeClient(owner, repo, self.gitee_token)
            print("repo is public")

        # collect pull request
        pull_data = self.getGenerator(
            client.pulls(state='all', once_update_num_of_pr=once_update_num_of_pr, direction='desc',
                         sort='updated', since=from_date))
        print(('collection %d pulls' % (len(pull_data))))
        for x in pull_data:
            actions = ""
            print('pull number = ', x['number'])
            if common.str_to_datetime(x['updated_at']) < from_date:
                continue
            if x['user']['login'] in self.skip_user:
                continue

            pr_number = x['number']

            pull_code_diff = self.getGenerator(client.pull_code_diff(pr_number))
            pull_action_logs = self.getGenerator(client.pull_action_logs(pr_number))
            pull_review_comments = self.getGenerator(client.pull_review_comments(pr_number))
            pull_commits = self.getGenerator(client.pull_commits(pr_number))

            codediffadd = 0
            codediffdelete = 0
            for item in pull_code_diff:
                if isinstance(item, dict):
                    codediffadd = int(codediffadd) + int(item['additions'])
                    codediffdelete = int(codediffdelete) + int(item['deletions'])
            merged_item = None
            if x['state'] == "closed":
                if isinstance(pull_action_logs, list):
                    try:
                        merged_item = pull_action_logs[0]
                    except IndexError as e:
                        print("pull number(%s) action log get failed in repo(%s)" % (x['number'], repo))
                        merged_item = None
                else:
                    merged_item = pull_action_logs
            x['codediffadd'] = codediffadd
            x['codediffdelete'] = codediffdelete
            eitem = self.__get_rich_pull(x, merged_item)
            actions += self.write_pull_commit_data(pull_commits, eitem, owner, sig_names)

            ecomments = self.get_rich_pull_reviews(pull_review_comments, eitem, owner)
            res_comment = self.write_comment_data(ecomments, eitem, sig_names, data_type='pull')
            actions += res_comment[0]
            try:
                comment_times = res_comment[1]
                if comment_times and len(comment_times) != 0:
                    firstreplyprtime = min(comment_times)
                    lastreplyprtime = max(comment_times)
                    eitem['firstreplyprtime'] = (datetime.datetime.strptime(
                        firstreplyprtime, '%Y-%m-%dT%H:%M:%S+08:00') - datetime.datetime.strptime(
                        eitem['created_at'], '%Y-%m-%dT%H:%M:%S+08:00')).total_seconds()
                    eitem['lastreplyprtime'] = (datetime.datetime.now() + datetime.timedelta(hours=8) - (
                        datetime.datetime.strptime(lastreplyprtime, '%Y-%m-%dT%H:%M:%S+08:00'))).total_seconds()
                else:
                    eitem['time_to_not_reply'] = (datetime.datetime.now() + datetime.timedelta(hours=8) - (
                        datetime.datetime.strptime(eitem['created_at'], '%Y-%m-%dT%H:%M:%S+08:00'))).total_seconds()
            except Exception as e:
                print(e)
                print(eitem['created_at'])
            eitem['prcommentscount'] = len(ecomments)
            if self.sig_index:
                eitem['pulls_signames'] = self.esClient.getRepoSigNames(self.sig_index, owner + "/" + repo)
                eitem['sig_names'] = sig_names
            if res_comment[2]:
                eitem['responsible_user_login'] = res_comment[2]
            indexData = {"index": {"_index": self.index_name, "_id": eitem['id']}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(eitem) + '\n'
            self.esClient.safe_put_bulk(actions)

        endTime = datetime.datetime.now()
        print("Collect pull request data finished, spend %s seconds" % (
                endTime - startTime).total_seconds())

    def write_pull_commit_data(self, pull_commits, eitem, owner, sig_names):
        actions = ''
        ecommits = self.get_rich_pull_commits(pull_commits, eitem, owner)
        for ec in ecommits:
            ec['sig_names'] = sig_names
            indexData = {
                "index": {"_index": self.index_name, "_id": 'commit_' + ec['sha']}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(ec) + '\n'
        return actions

    def writeIssueData(self, owner, repo, public, from_date=None, sig_names=None):
        startTime = datetime.datetime.now()
        client = GiteeClient(owner, repo, self.gitee_token)
        from_date = self.getFromDate(from_date, [
            {"name": "is_gitee_issue", "value": 1},
            {"name": "gitee_repo.keyword", "value": "https://gitee.com/" + owner + "/" + repo}])
        print("Start collect repo(%s/%s) issue data from %s" % (
            owner, repo, from_date))

        # common.
        if public:
            client = GiteeClient(owner, repo, self.gitee_token)
            print("repo is public")

        # collect issue
        actions = ""
        issue_data = self.getGenerator(client.issues(from_date))
        for i in issue_data:
            user = i.get('user', {})
            if user.get('login') in self.blacklist_user:
                continue

            print(str(i['number']))
            issue_comments = self.getGenerator(client.issue_comments(i['number']))
            i['comments_data'] = issue_comments
            issue_item = self.get_rich_issue(i)
            issue_comments = self.get_rich_issue_comments(issue_comments, issue_item)
            res_comment = self.write_comment_data(issue_comments, issue_item, sig_names, data_type='issue')
            try:
                comment_times = res_comment[1]
                actions += res_comment[0]
                if comment_times and len(comment_times) != 0:
                    firstreplyissuetime = min(comment_times)
                    lastreplyissuetime = max(comment_times)
                    issue_item['firstreplyissuetime'] = (datetime.datetime.strptime(
                        firstreplyissuetime, '%Y-%m-%dT%H:%M:%S+08:00') - datetime.datetime.strptime(
                        issue_item['created_at'], '%Y-%m-%dT%H:%M:%S+08:00')).total_seconds()
                    issue_item['lastreplyissuetime'] = (datetime.datetime.now() + datetime.timedelta(hours=8) - (
                        datetime.datetime.strptime(lastreplyissuetime, '%Y-%m-%dT%H:%M:%S+08:00'))).total_seconds()
                else:
                    issue_item['time_to_not_reply'] = (datetime.datetime.now() + datetime.timedelta(hours=8) - (
                        datetime.datetime.strptime(issue_item['created_at'], '%Y-%m-%dT%H:%M:%S+08:00'))).total_seconds()
            except Exception as e:
                print(e)
            issue_item['sig_names'] = sig_names
            index_id = 'issue_%s' % issue_item['id']
            if res_comment[2]:
                issue_item['responsible_user_login'] = res_comment[2]
            indexData = {"index": {"_index": self.index_name, "_id": index_id}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(issue_item) + '\n'

        self.esClient.safe_put_bulk(actions)
        endTime = datetime.datetime.now()
        print("Collect repo(%s/%s) issue data finished, spend %s seconds" % (
            owner, repo, (endTime - startTime).total_seconds()))

    def write_comment_data(self, ecomments, eitem, sig_names, data_type):
        if data_type == 'pull':
            id_str = 'pull_comment_id'
        else:
            id_str = 'issue_comment_id'
        ecomments.sort(key=lambda x: (x['created_at'] if x['created_at'] else '-1'))
        actions = ''
        comment_times = []
        creator_comments = []
        commenter_comments = []
        responsible = []
        last_reply_time = eitem.get('created_at')
        tag_sig_names = eitem.get('tag_sig_names')
        responsible = self.get_responsible(ecomments)
        for ec in ecomments:
            if ec['user_login'] is None:  # or ec['user_login'] in self.skip_user:
                continue

            if ec['user_login'] != eitem.get('user_login') and eitem.get('created_at') \
                    and ec['user_login'] not in self.robot_user_logins \
                    and not ec['body'].startswith('/sig'):
                comment_times.append(str(ec['created_at']))

            if ec['user_login'] == eitem.get('user_login'):
                creator_comments.append(ec)
            else:
                ec['time_to_reply'] = (datetime.datetime.strptime(
                        ec['created_at'], '%Y-%m-%dT%H:%M:%S+08:00') - datetime.datetime.strptime(
                        last_reply_time, '%Y-%m-%dT%H:%M:%S+08:00')).total_seconds()
                last_reply_time = ec['created_at']
                commenter_comments.append(ec)
        actions += self.write_comment_by_role(commenter_comments, sig_names, tag_sig_names, id_str, role='commenter')
        actions += self.write_comment_by_role(creator_comments, sig_names, tag_sig_names, id_str, role='creator')
        return actions, comment_times, responsible

    def write_comment_by_role(self, comments, sig_names, tag_sig_names, id_str, role):
        index = 0
        actions = ''
        for ec in comments:
            index += 1
            if role == 'commenter' and index == len(comments):
                ec['is_first_reply'] = 1
            ec['role_type_of_comment_user'] = role
            ec['sig_names'] = sig_names
            ec['tag_sig_names'] = tag_sig_names
            indexData = {
                "index": {"_index": self.index_name, "_id": ec[id_str]}}
            actions += json.dumps(indexData) + '\n'
            actions += json.dumps(ec) + '\n'
        return actions

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
                    # if isinstance(data, dict):
                    #     data = []
                    break
        except StopIteration:
            return data
        except JSONDecodeError:
            print("Gitee get JSONDecodeError, error: ", response)
        except Exception as ex:
            print('*** getGenerator fail ***', ex)
            return data

        return data

    def get_rich_pull_reviews(self, comments, eitem, owner=None):
        ecomments = []

        for comment in comments:
            ecomment = {}
            # Copy data from the enriched pull
            ecomment['pull_labels'] = eitem['pull_labels']
            ecomment['pull_id'] = eitem['pull_id']
            ecomment['pull_id_in_repo'] = eitem['pull_id_in_repo']
            ecomment['issue_id_in_repo'] = eitem['issue_id_in_repo']
            ecomment['issue_title'] = eitem['issue_title']
            ecomment['issue_url'] = eitem['issue_url']
            ecomment['pull_url'] = eitem['pull_url']
            ecomment['pull_state'] = eitem['pull_state']
            ecomment['pull_created_at'] = eitem['pull_created_at']
            ecomment['pull_updated_at'] = eitem['pull_updated_at']

            ecomment['base_label'] = eitem['base_label']
            ecomment['base_label_ref'] = eitem['base_label_ref']
            ecomment['head_label'] = eitem['head_label']
            ecomment['head_label_ref'] = eitem['head_label_ref']

            if 'pull_merged_at' in eitem:
                ecomment['pull_merged_at'] = eitem['pull_merged_at']
            if 'pull_closed_at' in eitem:
                ecomment['pull_closed_at'] = eitem['pull_closed_at']
            # ecomment['pull_merged'] = eitem['pull_merged']
            ecomment['pull_state'] = eitem['pull_state']
            ecomment['gitee_repo'] = eitem['gitee_repo']
            ecomment['repository'] = eitem['repository']
            ecomment['item_type'] = COMMENT_TYPE
            ecomment['sub_type'] = REVIEW_COMMENT_TYPE
            ecomment['org_name'] = owner

            # Copy data from the raw comment
            ecomment['url'] = comment['html_url']
            ecomment['comment_url'] = comment['html_url']
            ecomment['body'] = comment['body']

            user = comment.get('user', None)
            if user is not None and user:
                ecomment['user_name'] = user['name']
                ecomment['author_name'] = user['name']
                ecomment['user_login'] = user['login']
                ecomment['user_id'] = user['id']
                ecomment["user_domain"] = None
            # extract reactions and add it to enriched item
            # ecomment.update(self.__get_reactions(comment))

            ecomment['created_at'] = comment['created_at']
            ecomment['updated_at'] = comment['updated_at']
            ecomment['comment_updated_at'] = comment['updated_at']
            # ecomment['first_contribute_at'] = get_first_contribute_at(ecomment['author_name'], comment['created_at'])
            # Add id info to allow to coexistence of items of different types in the same index
            ecomment['pull_comment_id'] = '{}_review_comment_{}'.format(eitem['id'], comment['id'])
            ecomment['id'] = comment['id']
            # ecomment.update(self.get_grimoire_fields(comment['updated_at'], REVIEW_COMMENT_TYPE))
            # due to backtrack compatibility, `is_gitee2_*` is replaced with `is_gitee_*`

            if self.is_invalid_comment(ecomment['body']):
                ecomment['is_invalid_comment'] = 1

            ecomment['is_gitee_{}'.format(REVIEW_COMMENT_TYPE)] = 1
            ecomment['is_gitee_comment'] = 1

            userExtra = self.esClient.getUserInfo(ecomment['user_login'], comment['created_at'])
            ecomment.update(userExtra)
            ecomments.append(ecomment)

        return ecomments

    def get_rich_pull_commits(self, commits, eitem, owner=None):
        ecommits = []
        for commit in commits:
            ecommit = {}
            # Copy data from the enriched pull
            ecommit['pull_labels'] = eitem['pull_labels']
            ecommit['pull_id'] = eitem['pull_id']
            ecommit['pull_id_in_repo'] = eitem['pull_id_in_repo']
            ecommit['issue_id_in_repo'] = eitem['issue_id_in_repo']
            ecommit['issue_title'] = eitem['issue_title']
            ecommit['issue_url'] = eitem['issue_url']
            ecommit['pull_url'] = eitem['pull_url']
            ecommit['pull_state'] = eitem['pull_state']
            ecommit['pull_created_at'] = eitem['pull_created_at']
            ecommit['pull_updated_at'] = eitem['pull_updated_at']

            ecommit['base_label'] = eitem['base_label']
            ecommit['base_label_ref'] = eitem['base_label_ref']
            ecommit['head_label'] = eitem['head_label']
            ecommit['head_label_ref'] = eitem['head_label_ref']

            if 'pull_merged_at' in eitem:
                ecommit['pull_merged_at'] = eitem['pull_merged_at']
            if 'pull_closed_at' in eitem:
                ecommit['pull_closed_at'] = eitem['pull_closed_at']
            # ecommit['pull_merged'] = eitem['pull_merged']
            ecommit['pull_state'] = eitem['pull_state']
            ecommit['gitee_repo'] = eitem['gitee_repo']
            ecommit['repository'] = eitem['repository']
            ecommit['item_type'] = COMMIT_TYPE
            ecommit['org_name'] = owner

            # Copy data from the raw commit
            ecommit['url'] = commit['html_url']
            ecommit['commit_url'] = commit['html_url']
            ecommit['sha'] = commit['sha']

            committer = commit.get('committer', None)
            author = commit.get('author', None)
            if len(committer) == 0:
                continue
            if author is not None and author:
                ecommit['author_name'] = author['name']
            if committer is not None and committer:
                ecommit['committer_name'] = committer['name']
                ecommit['user_login'] = committer['login']
                ecommit['user_id'] = committer['id']
                ecommit["user_domain"] = None

            ecommit['created_at'] = commit['commit']['committer']['date']

            # due to backtrack compatibility, `is_gitee2_*` is replaced with `is_gitee_*`
            ecommit['is_gitee_{}'.format(COMMIT_TYPE)] = 1
            ecommit['is_gitee_commit'] = 1

            userExtra = self.esClient.getUserInfo(ecommit['user_login'], ecommit['created_at'])
            ecommit.update(userExtra)
            ecommits.append(ecommit)

        return ecommits

    def __get_rich_pull(self, item, merged_item):
        rich_pr = {}

        # The real data
        pull_request = item

        rich_pr['time_to_close_days'] = \
            common.get_time_diff_days(pull_request['created_at'], pull_request['closed_at'])
        rich_pr['time_to_close_seconds'] = \
            common.get_time_diff_seconds(pull_request['created_at'], pull_request['closed_at'])

        if pull_request['state'] != 'closed' or pull_request['state'] != 'merged':
            rich_pr['time_open_days'] = \
                common.get_time_diff_days(pull_request['created_at'],
                                          (common.datetime_utcnow() + datetime.timedelta(hours=8)).replace(tzinfo=None))
        else:
            rich_pr['time_open_days'] = rich_pr['time_to_close_days']

        rich_pr['user_login'] = pull_request['user']['login']

        user = pull_request.get('user', None)
        if user is not None and user:
            rich_pr['user_name'] = user['name']
            rich_pr['author_name'] = user['name']
            rich_pr['user_id'] = user['id']
            # rich_pr["user_domain"] = self.get_email_domain(user['email']) if user['email'] else None
            rich_pr["user_domain"] = None
        else:
            rich_pr['user_name'] = None
            rich_pr["user_domain"] = None
            rich_pr['author_name'] = None
            rich_pr['user_id'] = None

        if merged_item is not None and 'user' in merged_item:
            rich_pr['merge_author_login'] = merged_item['user']['login']
            rich_pr['merge_author_name'] = merged_item['user']['name']
            # rich_pr["merge_author_domain"] = self.get_email_domain(merged_by['email']) if merged_by['email'] else None
            rich_pr["merge_author_domain"] = None
        else:
            rich_pr['merge_author_name'] = None
            rich_pr['merge_author_login'] = None
            rich_pr["merge_author_domain"] = None

        rich_pr['id'] = pull_request['id']
        rich_pr['body'] = pull_request['body']
        rich_pr['pull_id'] = pull_request['id']
        rich_pr['pull_id_in_repo'] = pull_request['html_url'].split("/")[-1]
        rich_pr['repository'] = pull_request['url']

        client = GiteeClient("", "", self.gitee_token)
        issue_data = client.getIssueDetailsByPRUrl(pull_request['issue_url'])
        if len(issue_data) == 0:
            rich_pr['is_pr_associate_issue'] = 0
            rich_pr['issue_url'] = None
            rich_pr['issue_id_in_repo'] = None
            rich_pr['issue_title'] = None
            rich_pr['issue_title_analyzed'] = None
            rich_pr['issue_body'] = None
        else:
            rich_pr['issue_url'] = issue_data[0]['url']
            rich_pr['issue_id_in_repo'] = issue_data[0]['url'].split("/")[-1]
            rich_pr['issue_title'] = issue_data[0]['title']
            rich_pr['issue_title_analyzed'] = issue_data[0]['title']
            rich_pr['issue_body'] = issue_data[0]['body']
            rich_pr['is_pr_associate_issue'] = 1

        rich_pr['pull_title'] = pull_request['title']
        if self.invalid_pr_title and self.mark_invalid_pr_by_title(title=pull_request['title']):
            rich_pr['is_invalid_pr'] = 1
        rich_pr['pull_state'] = pull_request['state']
        if rich_pr['pull_state'] == 'open':
            rich_pr["is_pull_state_open"] = 1
        elif rich_pr['pull_state'] == 'closed':
            rich_pr["is_pull_state_closed"] = 1
        elif rich_pr['pull_state'] == 'merged':
            rich_pr["is_pull_state_merged"] = 1
        rich_pr['pull_created_at'] = pull_request['created_at']
        rich_pr['pull_updated_at'] = pull_request['updated_at']
        rich_pr['created_at'] = pull_request['created_at']
        rich_pr['updated_at'] = pull_request['updated_at']
        # rich_pr['first_contribute_at'] = get_first_contribute_at(rich_pr['user_name'], pull_request['created_at'])

        if pull_request['merged_at'] and pull_request['merged_at'] is not None:
            rich_pr['pull_merged_at'] = pull_request['merged_at']
        if pull_request['closed_at'] and pull_request['closed_at'] is not None:
            rich_pr['pull_closed_at'] = pull_request['closed_at']
        rich_pr['url'] = pull_request['html_url']
        rich_pr['pull_url'] = pull_request['html_url']
        # rich_pr['issue_url'] = pull_request['html_url']

        labels = []
        [labels.append(label['name']) for label in pull_request['labels'] if 'labels' in pull_request]
        rich_pr['pull_labels'] = labels
        rich_pr['tag_sig_names'] = self.get_tag_sig(labels)

        rich_pr['item_type'] = PULL_TYPE

        # rich_pr['gitee_repo'] = rich_pr['repository'].replace(gitee, '')
        rich_pr['gitee_repo'] = re.sub('.git$', '', pull_request['base']['repo']['html_url'])
        rich_pr['org_name'] = pull_request['base']['repo']['namespace']['path']

        rich_pr['base_label'] = pull_request['base']['label']
        rich_pr['base_label_ref'] = pull_request['base']['ref']
        rich_pr['head_label'] = pull_request['head']['label']
        rich_pr['head_label_ref'] = pull_request['head']['ref']
        # GMD code development metrics
        # rich_pr['forks'] = pull_request['base']['repo']['forks_count']
        rich_pr['code_merge_duration'] = common.get_time_diff_days(pull_request['created_at'],
                                                                   pull_request['merged_at'])
        # rich_pr['num_review_comments'] = pull_request['review_comments']

        # rich_pr['time_to_merge_request_response'] = None
        # if pull_request['review_comments'] != 0:
        #    min_review_date = self.get_time_to_merge_request_response(pull_request)
        #    rich_pr['time_to_merge_request_response'] = \
        #        get_time_diff_days(str_to_datetime(pull_request['created_at']), min_review_date)

        # if self.prjs_map:
        #    rich_pr.update(self.get_item_project(rich_pr))
        userExtra = self.esClient.getUserInfo(rich_pr['user_login'], pull_request['created_at'])
        rich_pr.update(userExtra)
        pr_author = self.refresh_sync_pr_author(rich_pr['body'], rich_pr['pull_url'])
        rich_pr.update(pr_author)
        rich_pr['addcodenum'] = pull_request['codediffadd']
        rich_pr['deletecodenum'] = pull_request['codediffdelete']
        if 'project' in item:
            rich_pr['project'] = item['project']

        rich_pr['is_gitee_{}'.format(PULL_TYPE)] = 1

        return rich_pr

    def refresh_sync_pr_author(self, pull_url, body):
        user = {}
        if body and 'Origin pull request:' in body:
            try:
                client = GiteePrVersion(self.config)
                client.index_name_gitee = self.index_name
                prs = body.split('Origin pull request:')
                origin_pr = prs[1].split('###')[0].strip()
                user = client.get_origin_pr_author(origin_pr)
            except Exception:
                print(f'parse pr author error: {pull_url}')
        return user
    
    def mark_invalid_pr_by_title(self, title):
        for item in self.invalid_pr_title.split(";"):
            if str(title).__contains__(item):
                return True
        return False

    def get_rich_issue(self, item):
        rich_issue = {}
        # The real data
        issue = item

        rich_issue['time_to_close_days'] = \
            common.get_time_diff_days(issue['created_at'], issue['finished_at'])
        rich_issue['time_to_close_seconds'] = \
            common.get_time_diff_seconds(issue['created_at'], issue['finished_at'])

        if issue['state'] != 'closed':
            rich_issue['time_open_days'] = \
                common.get_time_diff_days(issue['created_at'],
                                          (common.datetime_utcnow() + datetime.timedelta(hours=8)).replace(tzinfo=None))
        else:
            rich_issue['time_open_days'] = rich_issue['time_to_close_days']

        # rich_issue['user_login'] = issue['user']['login']

        user = issue.get('user', None)
        if user is not None and user:
            rich_issue['user_id'] = user['id']
            rich_issue['user_name'] = user['name']
            rich_issue['author_name'] = user['name']
            rich_issue['user_login'] = user['login']
            # rich_issue["user_domain"] = self.get_email_domain(user['email']) if user['email'] else None
            # rich_issue['user_org'] = user['company']
            # rich_issue['user_location'] = user['location']
            # rich_issue['user_geolocation'] = None
        milestone = issue.get('milestone', None)
        if milestone is not None and milestone:
            rich_issue['milestone_url'] = milestone['url']
            rich_issue['milestone_html_url'] = milestone['html_url']
            rich_issue['milestone_id'] = milestone['id']
            rich_issue['milestone_number'] = milestone['number']
            rich_issue['milestone_repository_id'] = milestone['repository_id']
            rich_issue['milestone_state'] = milestone['state']
            rich_issue['milestone_title'] = milestone['title']
            rich_issue['milestone_description'] = milestone['description']
            rich_issue['milestone_updated_at'] = milestone['updated_at']
            rich_issue['milestone_created_at'] = milestone['created_at']
            rich_issue['milestone_open_issues'] = milestone['open_issues']
            rich_issue['milestone_closed_issues'] = milestone['closed_issues']
            rich_issue['milestone_due_on'] = milestone['due_on']
        else:
            rich_issue['milestone_url'] = None
            rich_issue['milestone_html_url'] = None
            rich_issue['milestone_id'] = None
            rich_issue['milestone_number'] = None
            rich_issue['milestone_repository_id'] = None
            rich_issue['milestone_state'] = None
            rich_issue['milestone_title'] = 'NA'
            rich_issue['milestone_description'] = None

        assignee = issue.get('assignee', None)
        if assignee and assignee is not None:
            assignee = issue['assignee']
            rich_issue['assignee_login'] = assignee['login']
            rich_issue['assignee_name'] = assignee['name']
            # rich_issue["assignee_domain"] = self.get_email_domain(assignee['email']) if assignee['email'] else None
            # rich_issue['assignee_org'] = assignee['company']
            # rich_issue['assignee_location'] = assignee['location']
            # rich_issue['assignee_geolocation'] = None
        else:
            rich_issue['assignee_name'] = None
            rich_issue['assignee_login'] = None
            # rich_issue["assignee_domain"] = None
            # rich_issue['assignee_org'] = None
            # rich_issue['assignee_location'] = None
            # rich_issue['assignee_geolocation'] = None

        rich_issue['id'] = issue['id']
        rich_issue['body'] = issue['body']
        rich_issue['plan_started_at'] = issue['plan_started_at']
        rich_issue['deadline'] = issue['deadline']
        # 获取issue严重级别
        rich_issue['priority'] = issue['priority']
        rich_issue['issue_id'] = issue['id']
        rich_issue['issue_number'] = issue['number']
        rich_issue['issue_id_in_repo'] = issue['html_url'].split("/")[-1]
        rich_issue['repository'] = issue['repository']['full_name']
        rich_issue['repository_forks_count'] = int(issue['repository']['forks_count'])
        rich_issue['repository_stargazers_count'] = int(issue['repository']['stargazers_count'])
        rich_issue['repository_watchers_count'] = int(issue['repository']['watchers_count'])
        rich_issue['issue_title'] = issue['title']
        rich_issue['issue_title_analyzed'] = issue['title']
        rich_issue['issue_state'] = issue['state']
        rich_issue['issue_type'] = issue['issue_type']
        if (rich_issue['issue_state'] == 'progressing'):
            rich_issue['is_issue_state_progressing'] = 1
        elif (rich_issue['issue_state'] == 'open'):
            rich_issue['is_issue_state_open'] = 1
        elif (rich_issue['issue_state'] == 'closed'):
            rich_issue['is_issue_state_closed'] = 1
        elif (rich_issue['issue_state'] == 'rejected'):
            rich_issue['is_issue_state_rejected'] = 1
        rich_issue['issue_created_at'] = issue['created_at']
        rich_issue['issue_updated_at'] = issue['updated_at']
        rich_issue['issue_closed_at'] = issue['finished_at']
        rich_issue['created_at'] = issue['created_at']
        rich_issue['updated_at'] = issue['updated_at']
        rich_issue['closed_at'] = issue['finished_at']
        rich_issue['url'] = issue['html_url']
        rich_issue['issue_url'] = issue['html_url']
        rich_issue['issue_customize_state'] = issue['issue_state']

        # extract reactions and add it to enriched item

        labels = []
        [labels.append(label['name']) for label in issue['labels'] if 'labels' in issue]
        rich_issue['issue_labels'] = labels
        rich_issue['tag_sig_names'] = self.get_tag_sig(labels)

        rich_issue['item_type'] = ISSUE_TYPE
        rich_issue['issue_pull_request'] = True
        if 'head' not in issue.keys() and 'pull_request' not in issue.keys():
            rich_issue['issue_pull_request'] = False

        rich_issue['gitee_repo'] = re.sub('.git$', '', issue['repository']['html_url'])
        rich_issue['org_name'] = issue['repository']['namespace']['path']
        # if self.prjs_map:
        #    rich_issue.update(self.get_item_project(rich_issue))

        if 'project' in issue:
            rich_issue['project'] = issue['project']

        rich_issue['time_to_first_attention'] = None
        if issue['comments'] != 0:
            rich_issue['time_to_first_attention'] = \
                common.get_time_diff_days(common.str_to_datetime(issue['created_at']),
                                          common.get_time_to_first_attention(issue))

        rich_issue['is_gitee_{}'.format(ISSUE_TYPE)] = 1

        userExtra = self.esClient.getUserInfo(rich_issue['user_login'], issue['created_at'])
        rich_issue.update(userExtra)
        return rich_issue

    def get_rich_issue_comments(self, comments, eitem):
        ecomments = []

        for comment in comments:
            ecomment = {}

            # Copy data from the enriched issue
            ecomment['issue_labels'] = eitem['issue_labels']
            ecomment['org_name'] = eitem['org_name']
            ecomment['issue_id'] = eitem['issue_id']
            ecomment['issue_number'] = eitem['issue_number']
            ecomment['issue_id_in_repo'] = eitem['issue_id_in_repo']
            ecomment['issue_url'] = eitem['issue_url']
            ecomment['issue_title'] = eitem['issue_title']
            ecomment['issue_state'] = eitem['issue_state']
            ecomment['issue_created_at'] = eitem['issue_created_at']
            ecomment['issue_updated_at'] = eitem['issue_updated_at']
            ecomment['issue_closed_at'] = eitem['issue_closed_at']
            ecomment['closed_at'] = eitem['issue_closed_at']
            ecomment['issue_pull_request'] = eitem['issue_pull_request']
            ecomment['gitee_repo'] = eitem['gitee_repo']
            ecomment['repository'] = eitem['repository']
            ecomment['repository_forks_count'] = eitem['repository_forks_count']
            ecomment['repository_stargazers_count'] = eitem['repository_stargazers_count']
            ecomment['repository_watchers_count'] = eitem['repository_watchers_count']
            ecomment['item_type'] = COMMENT_TYPE
            ecomment['sub_type'] = ISSUE_COMMENT_TYPE

            # Copy data from the raw comment
            # ecomment['url'] = comment['html_url']

            # extract reactions and add it to enriched item
            user = comment.get('user', None)
            if user is not None and user:
                ecomment['user_id'] = user['id']
                ecomment['user_name'] = user['name']
                ecomment['author_name'] = user['name']
                ecomment['user_login'] = user['login']
                ecomment["user_domain"] = None

            ecomment['body'] = comment['body']
            ecomment['created_at'] = comment['created_at']
            ecomment['updated_at'] = comment['updated_at']
            ecomment['issue_comment_updated_at'] = comment['updated_at']
            ecomment['comment_updated_at'] = comment['updated_at']
            # ecomment['first_contribute_at'] = get_first_contribute_at(ecomment['author_name'], comment['created_at'])
            # Add id info to allow to coexistence of items of different types in the same index
            ecomment['issue_comment_id'] = '{}_issue_comment_{}'.format(eitem['issue_id'], comment['id'])
            ecomment['id'] = comment['id']
            ecomment['is_gitee_{}'.format(ISSUE_COMMENT_TYPE)] = 1
            ecomment['is_gitee_comment'] = 1

            if self.is_invalid_comment(ecomment['body']):
                ecomment['is_invalid_comment'] = 1

            if 'project' in eitem:
                ecomment['project'] = eitem['project']
            userExtra = self.esClient.getUserInfo(ecomment['user_login'], comment['created_at'])
            ecomment.update(userExtra)
            # self.add_repository_labels(ecomment)
            # self.add_metadata_filter_raw(ecomment)
            # self.add_gelk_metadata(ecomment)

            ecomments.append(ecomment)

        return ecomments

    def getUserInfo(self, login):
        userExtra = {}
        if self.is_gitee_enterprise == 'true':
            if login in self.enterpriseUsers:
                userExtra["tag_user_company"] = self.internal_company_name
                userExtra["is_project_internal_user"] = 1
            else:
                userExtra["tag_user_company"] = "n/a"
                userExtra["is_project_internal_user"] = 0
        else:
            if login in self.internalUsers:
                userExtra["tag_user_company"] = self.internal_company_name
                userExtra["is_project_internal_user"] = 1
            else:
                userExtra["tag_user_company"] = "n/a"
                userExtra["is_project_internal_user"] = 0

        return userExtra

    def updateIsFirstCountributeItem(self):
        all_user = self.esClient.getTotalAuthorName(
            field="user_login.keyword")
        for user in all_user:
            user_name = user["key"]
            print("start to update user:", user)
            self.esClient.setIsFirstCountributeItem(user_name)

    def updateCreatedRepoAuthor(self):
        client = GiteeClient("openeuler", "community", self.gitee_token)
        data = self.getGenerator(client.pulls(state='merged'))

        for d in data:
            print("updateCreatedRepoAuthor pull request number=%d" % d["number"])
            pull_files = self.getGenerator(client.pull_files(d["number"]))
            for p in pull_files:
                if p["filename"] != "repository/src-openeuler.yaml" \
                        and p["filename"] != "repository/openeuler.yaml":
                    continue

                lines = p["patch"]["diff"].split("\n")
                for line in lines:
                    if "+- name: " not in line:
                        continue
                    repo_name = line.split("+- name: ")[1]
                    print(repo_name)

                    author_name = d['base']['user']['name']
                    user_login = d['base']['user']['login']
                    print(author_name)
                    is_internal = False
                    if user_login in self.internalUsers:
                        is_internal = True
                    self.esClient.updateRepoCreatedName(
                        p["filename"].split('/')[1].split('.')[0], repo_name,
                        author_name, user_login, is_internal)

    def getAllIndex(self, user):
        matchs = [{
            "name": "user_login.keyword",
            "value": user,
        }]
        data = self.esClient.getItemsByMatchs(matchs, size=0)
        if len(data) == 0:
            return []
        all_count = data["hits"]["total"]["value"]
        print("get %d items from user %s" % (all_count, user))
        if all_count < 1:
            return []

        aggs = '''"aggs": {
            "uniq_gender": {
                "terms": {
                    "field": "_id",
                    "size": %s
                }
            }
        }''' % all_count
        ids = self.esClient.getItemsByMatchs(matchs, size=0, aggs=aggs)

        print("update %d buckets for user %s" % (len(ids['aggregations']["uniq_gender"]["buckets"]), user))
        return ids['aggregations']["uniq_gender"]["buckets"]

    def getItselfUsers(self, filename="users"):
        f = open(filename, 'r', encoding="utf-8")

        users = []
        for line in f.readlines():
            if line != "\n":
                users.append(line.split('\n')[0])
        print(users)
        return users

    def tagHistoryUsers(self):
        if self.giteeid_company_dict_last == self.esClient.giteeid_company_dict:
            return

        if self.is_gitee_enterprise == "true":
            users = self.enterpriseUsers
        else:
            users = self.internalUsers

        dict_all_user = {}
        # the first update all data
        if len(self.giteeid_company_dict_last) == 0:
            all_user = self.esClient.getTotalAuthorName(size=50000)
            for user in all_user:
                dict_all_user.update({user['key']: "independent"})

        diff = self.esClient.giteeid_company_dict.items() - self.giteeid_company_dict_last.items()
        dele = self.giteeid_company_dict_last.keys() - self.esClient.giteeid_company_dict.keys()
        for d in dele:
            diff.add((d, "independent"))

        dict_all_user.update(dict(diff))
        for u, value in dict_all_user.items():
            sp = value.split("_adminAdded_", 1)
            company = sp[0]
            if len(sp) == 2:
                is_admin_added = sp[1]
            else:
                is_admin_added = 0
            if u in users or company == self.internal_company_name:
                is_project_internal_user = 1
                tag_user_company = self.internal_company_name
            else:
                is_project_internal_user = 0
                tag_user_company = company

            if len(self.esClient.giteeid_company_change_dict) != 0 and u in self.esClient.giteeid_company_change_dict:
                vMap = self.esClient.giteeid_company_change_dict[u]
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
                    print('*** update %s : %s' % (u, company))

                    query = '''{
                        "script": {
                            "source": "ctx._source.tag_user_company = params.tag_user_company;ctx._source.is_project_internal_user = params.is_project_internal_user;ctx._source.is_admin_added = params.is_admin_added",
                            "params": {
                                "tag_user_company": "%s",
                                "is_project_internal_user": "%s",
                                "is_admin_added": "%s"
                            },
                            "lang": "painless"
                        },
                        "query": {
                            "bool": {
                                "filter": [
                                    {
                                        "range": {
                                            "created_at": {
                                                "gte": "%s",
                                                "lt": "%s"
                                            }
                                        }
                                    },
                                    {
                                        "query_string": {
                                            "analyze_wildcard": true,
                                            "query": "user_login.keyword:%s AND !tag_user_company.keyword:%s"
                                        }
                                    }
                                ]
                            }
                        }
                    }''' % (company, is_project_internal_user, is_admin_added, startTime, endTime, u, company)
                    self.esClient.updateByQuery(query=query.encode('utf-8'))
            else:
                print('*** update %s : %s' % (u, tag_user_company))
                query = '''{
                    "script": {
                        "source": "ctx._source.tag_user_company = params.tag_user_company;ctx._source.is_project_internal_user = params.is_project_internal_user;ctx._source.is_admin_added = params.is_admin_added",
                        "params": {
                            "tag_user_company": "%s",
                            "is_project_internal_user": "%s",
                            "is_admin_added": "%s"
                        },
                        "lang": "painless"
                    },
                    "query": {
                        "bool": {
                            "filter": [
                                {
                                    "query_string": {
                                        "analyze_wildcard": true,
                                        "query": "user_login.keyword:%s AND !tag_user_company.keyword:%s"
                                    }
                                }
                            ]
                        }
                    }
                }''' % (tag_user_company, is_project_internal_user, is_admin_added, u, tag_user_company)
                self.esClient.updateByQuery(query=query.encode('utf-8'))

    def tagUsersFromEmail(self, tag_user_company="internal_company"):
        if self.is_gitee_enterprise == "true":
            users = self.enterpriseUsers
        else:
            users = self.internalUsers

        all_user = self.esClient.getTotalAuthorName(field="user_login.keyword")

        for user in all_user:
            u = user["key"]
            if u in self.skip_user:
                continue
            if u in users:
                tag_company = tag_user_company
                is_internal = 1
            else:
                tag_company = "independent"
                is_internal = 0

            if self.esClient.is_update_tag_company == 'true' and u in self.esClient.giteeid_company_dict:
                tag_company = self.esClient.giteeid_company_dict.get(u)
                if tag_company == self.internal_company_name:
                    is_internal = 1
                update_data = {
                    "doc": {
                        "tag_user_company": tag_company,
                        "is_project_internal_user": is_internal,
                    }
                }

            actions = ""
            ids = self.getAllIndex(u)
            for id in ids:
                action = common.getSingleAction(
                    self.index_name, id["key"], update_data, act="update")
                actions += action

            self.esClient.safe_put_bulk(actions)

    def tagUsers(self, from_date=None, tag_user_company="openeuler"):
        if self.is_gitee_enterprise == "true":
            users = self.enterpriseUsers
        else:
            users = self.internalUsers
        all_user = self.esClient.getTotalAuthorName(
            field="user_login.keyword")
        for user in all_user:
            u = user["key"]
            if u == "mindspore_ci":
                continue
            if u in users:
                update_data = {
                    "doc": {
                        "tag_user_company": tag_user_company,
                        "is_project_internal_user": 1,
                    }
                }
            else:
                update_data = {
                    "doc": {
                        "tag_user_company": "n/a",
                        "is_project_internal_user": 0,
                    }
                }
            if self.yaml_url:
                cmd = 'wget %s' % self.yaml_url
                os.popen(cmd)
                datas = yaml.load_all(open(self.yaml_path)).__next__()

                for data in datas:
                    if data['gitee_id'] == u:
                        if not data["companies"]['company_name'] and data['emails']:
                            for email in data['emails']:
                                if email.endswith('@huawei.com'):
                                    update_data["companies"]['company_name'] = 'Huawei'
                                    break
                        else:
                            if re.search(r'huawei', data["companies"]['company_name'], re.I):
                                update_data["companies"]['company_name'] = 'Huawei'
            actions = ""
            ids = self.getAllIndex(u)
            for id in ids:
                action = common.getSingleAction(
                    self.index_name, id["key"], update_data, act="update")
                actions += action

            self.esClient.safe_put_bulk(actions)

    def collectTotal(self, from_time):
        self.collectTotalByType(from_time, "is_gitee_pull_request")
        self.collectTotalByType(from_time, "is_gitee_issue")

    def collectTotalByType(self, from_time, type):
        matchs = [{"name": type, "value": 1}]
        from_date = datetime.datetime.strptime(from_time, "%Y%m%d")
        to_date = datetime.datetime.today()
        data = self.esClient.getCountByDateRange(matchs, from_date, to_date)
        print(data)
        actions = ""
        for d in data:
            print("date = %s, count = %s" % (
                d.get("to_as_string"), d.get("doc_count")))
            created_at = d.get("to_as_string")
            body = {
                "all_count": d.get("doc_count"),
                "created_at": created_at,
                "updated_at": created_at,
                type + "_total": 1
            }

            id = created_at + type + "_total"
            action = common.getSingleAction(self.index_name, id, body)
            actions += action
        self.esClient.safe_put_bulk(actions)

    def getEnterpriseUser(self):
        if self.is_gitee_enterprise != "true":
            return

        client = GiteeClient(self.orgs[0], "", self.gitee_token)

        data = self.getGenerator(client.enterprise_members())
        for d in data:
            user = d.get("user").get("login")
            print(user)
            self.enterpriseUsers.append(user)

    def getUserInfoFromDataFile(self):
        f = open('data.json')
        userInfos = json.load(f)
        alluserinfos = []
        for user in userInfos.get("users"):
            print(user.get('gitee_id'))
            print(user.get('github_id'))
            print(user.get('companies'))
            if user.get('gitee_id'):
                alluserinfos.append({user.get('gitee_id'): user})
        print(alluserinfos)
        self.all_user_info = alluserinfos

        for company in userInfos.get("companies"):
            for alia in company.get("aliases"):
                self.companyinfos[alia] = company.get("company_name")
            for domain in company.get("domains"):
                self.companyinfos[domain] = company.get("company_name")

    def getSartUsersList(self):
        if self.index_name_all:
            for index in range(len(self.orgs)):
                client = GiteeClient(self.orgs[index], "", self.gitee_token)
                respons = client.org_followers(self.orgs[index])

                for r in respons:
                    for user in json.loads(r):
                        id = self.orgs[index] + '_star_' + str(user['id'])
                        user['created_at'] = user['followed_at'].replace('Z', '+08:00')
                        user['is_set_sigs_star'] = 1
                        user['user_login'] = user['login']
                        user['user_id'] = user['id']
                        user['user_name'] = user['name']
                        user['author_name'] = user['name']
                        user['org_name'] = self.orgs[index]
                        user['gitee_repo'] = 'default'
                        userExtra = self.esClient.getUserInfo(user['login'], user['created_at'])
                        user.update(userExtra)
                        action = common.getSingleAction(self.index_name_all[index], id, user)
                        self.esClient.safe_put_bulk(action)

    def get_repo_sig(self, org, repo_name):
        sig_names = ['No-SIG']
        if org == 'opengauss':
            key = repo_name
        else:
            key = org + '/' + repo_name
        if key.lower() in self.repo_sigs_dict:
            sig_names = self.repo_sigs_dict[key.lower()]
        return sig_names

    def get_responsible(self, content_list):
        res_list = []
        for content in content_list:
            if content['user_login'] in self.robot_user_logins:
                content = str(content['body'])
                if not content.__contains__('please contact the owner in first:'):
                    continue
                sub_str = content.split('please contact the owner in first:')[1]
                subs = sub_str.split('and then any of the maintainers')[0]
                responsible = subs.split('@')
                res_list = []
                for r in responsible:
                    rs = r.split(',')
                    res_list.extend(rs)
                responsible_list = []
                for s in res_list:
                    if len(s.strip()) != 0:
                        responsible_list.append(s.strip())
                res_list = responsible_list
        return res_list

    def get_dict_key_lower(self, data_dict):
        res = {}
        for key in data_dict:
            res.update({key.lower(): data_dict.get(key)})
        return res

    def get_tag_sig(self, labels):
        sig = 'No-Sig'
        for label in labels:
            if label.startswith('sig/'):
                sig = label.split('/')[1]
                return sig
        return sig

    def is_invalid_comment(self, body):
        if not body.strip().startswith('/') and not body.strip().startswith('／'):
            return False
        for _char in body:
            if '\u4e00' <= _char <= '\u9fff':
                return False
        res = []
        strs = body.strip().split(' ')
        for s in strs:
            if s == '':
                continue
            on = s.split('\n')
            res.extend(on)

        words = []
        for r in res:
            if r == '':
                continue
            words .append(r)
        if len(words) < 3:
            return True
