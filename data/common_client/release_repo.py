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
# Create: 2024/10/15
import os

import yaml


class ReleaseRepo(object):
    def __init__(self, config):
        self.obs_meta_org = config.get('obs_meta_org')
        self.obs_meta_repo = config.get('obs_meta_repo')
        self.obs_meta_dir = config.get('obs_meta_dir')
        self.obs_versions = config.get('obs_versions')
        self.code_base_path = config.get('code_base_path')
        self.gitee_base = config.get('gitee_base')
        self.platform = config.get('platform')

    @staticmethod
    def remove_git_lock_file(code_path):
        lock_file = code_path + '/.git/index.lock'
        if os.path.exists(lock_file):
            os.remove(lock_file)

    @staticmethod
    def convert_dict(version_repos):
        repo_versions = {}

        for version, repos in version_repos.items():
            for repo in repos:
                if repo not in repo_versions:
                    repo_versions[repo] = [version]
                else:
                    repo_versions[repo].append(version)
        return repo_versions

    @staticmethod
    def get_version_repos(root, version: str):
        repos = []
        package_dirs = []
        try:
            package_path = os.path.join(root, version)
            if os.path.exists(package_path):
                _, package_dirs, _ = os.walk(package_path).__next__()
        except OSError as e:
            print('package_path error: ', e)
            return repos

        for pkg_dir in package_dirs:
            if pkg_dir == 'delete':
                continue
            repo_path = os.path.join(root, version, pkg_dir, 'pckg-mgmt.yaml')
            if not os.path.exists(repo_path):
                continue
            repo_info = yaml.safe_load(open(repo_path)).get('packages')
            for repo in repo_info:
                repo_name = repo.get('name')
                repos.append(repo_name)
        
        if not repos:
            repo_path = os.path.join(root, version, 'pckg-mgmt.yaml')
            if not os.path.exists(repo_path):
                return repos
            repo_info = yaml.safe_load(open(repo_path)).get('packages', {}).get('natural', [])
            for repo in repo_info:
                repo_name = repo.get('name')
                repos.append(repo_name)

        return list(set(repos))

    @staticmethod
    def get_version_repo_type(root, version: str):
        repo_types = {}
        package_dirs = []
        try:
            package_path = os.path.join(root, version)
            if os.path.exists(package_path):
                _, package_dirs, _ = os.walk(package_path).__next__()
        except OSError as e:
            print('package_path error: ', e)
            return repo_types

        for pkg_dir in package_dirs:
            if pkg_dir == 'delete':
                continue
            repo_path = os.path.join(root, version, pkg_dir, 'pckg-mgmt.yaml')
            repo_info = yaml.safe_load(open(repo_path)).get('packages')
            for repo in repo_info:
                repo_name = repo.get('name')
                repo_types.update({repo_name: pkg_dir})
        return repo_types

    def get_repo_versions(self):
        obs_path = self.git_clone_or_pull_repo(platform=self.platform, owner=self.obs_meta_org)
        meta_dir = obs_path if self.obs_meta_dir is None else os.path.join(obs_path, self.obs_meta_dir)
        root, dirs, _ = os.walk(meta_dir).__next__()

        def check_version(s):
            return s.startswith("openEuler-")

        inter_versions = list(filter(check_version, dirs))
        version_repos = {}
        for version in inter_versions:
            version_repos[version] = self.get_version_repos(root, version)
        return self.convert_dict(version_repos)

    def git_clone_or_pull_repo(self, platform, owner):
        # 本地仓库目录
        owner_path = os.path.join(self.code_base_path, platform, owner)
        if not os.path.exists(owner_path):
            os.makedirs(owner_path)
        repo_name = self.obs_meta_repo
        code_path = os.path.join(owner_path, repo_name)

        if platform == 'gitee':
            clone_url = f'{self.gitee_base}/{owner}/{repo_name}'
        else:
            clone_url = None

        # 本地仓库已存在执行git pull；否则执行git clone
        self.remove_git_lock_file(code_path)
        if os.path.exists(code_path):
            cmd_pull = 'cd %s;git checkout .;git pull --rebase' % code_path
            os.system(cmd_pull)
        else:
            if not clone_url:
                return
            cmd_clone = 'cd "%s";git clone %s' % (owner_path, clone_url + '.git')
            os.system(cmd_clone)
        return code_path
