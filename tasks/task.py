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


import logging
import os
import time
from configparser import ConfigParser

from tasks.utils import import_object

logger = logging.getLogger(__name__)

BACKEND_MAPPING = {
    'baidutongji': 'data.baidutongji.BaiduTongji',
    'gitee': 'data.gitee.Gitee',
    'gitee_event': 'data.gitee_event.GiteeEvent',
    'nginx': 'data.nginx.Nginx',
    'obs': 'data.obs.OBS',
    'mailman': 'data.mailman.MailMan',
    'sig': 'data.sig.SIG',
    'github_down': 'data.github_down.GitHubDown',
    'github_swf': 'data.github_swf.GitHubSWF',
    'huawei_swr': 'data.huawei_swr.HUAWEISWR',
    'users': 'data.combine.users.Users',
    'huaweicloud': 'data.huaweicloud.HuaweiCloud',
    'bilibili': 'data.bilibili.BILIBILI',
    'collect_data': 'data.collect_data.CollectData',
    'transform_data': 'data.transform_data.TransformData',
    'git_commit': 'data.git_commit.GitCommit',
    'cloc': 'data.cloc.ClocCode',
    'meetings': 'data.meetings.Meetings',
    'report_email': 'data.report_email.ReportEmail',
    'cve': 'data.cve.CVE',
    'cla': 'data.cla.Cla',
    'polymerization': 'data.combine.polymerization.Polymerization',
    'account_org': 'data.account_org.AccountOrg',
    'git': 'data.git_commit.GitCommit',
    'ru_download': 'data.ru_download.RuDownload',
    'meetup': 'data.meetup.Meetup',
    'github_pr_issue': 'data.github_pr_issue.GitHubPrIssue',
    'try_me': 'data.tryme.TryMe',
    'blue_zone_user': 'data.blue_zone_user.BlueZoneUser',
    'googleanalytic_user': 'data.googleanalytic_user.GoogleAnalyticUser',
    'up_down_ratio': 'data.combine.up_down_ratio.UpDownRatio',
    'build_obs': 'data.build_obs.OBS',
    'issue_rule_label': 'data.tag_labels.issue_rule_label.IssueRuleLabel',
    'prophet_prediction': 'data.time_series.prophet_prediction.ProphetPrediction',
    'user_relations': 'data.user_relations.UserRelations',
    'gitee_github_combine': 'data.combine.gitee_github_combine.GiteeGithubCombine',
    'surveys_tencent': 'data.surveys_tencent.SurveysTencent',
    'gitee_developer': 'data.gitee_developer.GiteeDeveloper',
    'activities_practice': 'data.activities_practice.ActivitiesPractice',
    'questionnaire': 'data.questionnaire.Questionnaire',
    'git_commit_log': 'data.git_commit_log.GitCommitLog',
    'sig_maintainer': 'data.sig_maintainer.SigMaintainer',
    'tag_removed_gitee': 'data.combine.tag_remove_gitee.TagRemovedGitee',
    'refresh_token': 'data.refresh_token.RefreshToken',
    'gitlab': 'data.gitlab.Gitlab',
    'gitee_metrics': 'data.gitee_metrics.GiteeMetrics',
    'giteescore': 'data.gitee_issue_score.GiteeScore',
    'collect_pypi': 'data.pypi.CollectPypi',
    'sigscores': 'data.time_series.sig_scores.SigScores',
    'company_location': 'data.combine.company_location.CompanyLocation',
    'ndcg': 'data.ndcg.Ndcg',
    'code_statistics': 'data.code_statistics.CodeStatistics',
    'rpm_repo_download': 'data.combine.rpm_repo_download.RpmRepoDownload',
    'xihe_downoload': 'data.xihe_download.XiheDown',
    'download_count': 'data.combine.download.DownloadCount',
    'search_repos': 'data.search_repos.SearchRepos',
    'ecosystem_repo': 'data.ecosystem_repo.EcosystemRepo',
    'docker_hub': 'data.docker_hub.DockerHub',
    'city_location': 'data.city_location.CityLocation',
    'gitee_pr_version': 'data.gitee_pr_version.GiteePrVersion',
    'eur_openeuler': 'data.eur_openeuler.EurOpenEuler',
    'eur_openeuler_download': 'data.eur_openeuler_download.EurOpenEulerDownload',
    'big_model_research': 'data.big_model_research.BigModelResearch',
    'forum_post': 'data.forum_post.ForumPost',
    'hub_oepkgs': 'data.hub_oepkgs.HubOepkgs',
    'swr': 'data.swr.Swr',
    'gitee_feature': 'data.gitee_feature.giteeFeature',
    'pypi_download': 'data.pypi_download.PypiDownload',
    'package_status': 'data.package.package_status.PackageStatus',
    'package_maintenance': 'data.package.package_maintenance.PackageStatus',
    'package_overview': 'data.package.package_overview.PackageOverview',
    'github_account': 'data.github_account.GitHubAccount',
    'export_task': 'data.huawei_analytic.export_task.ExportTask',
    'openmind_owner': 'data.time_series.openmind_owner.OpenmindOwner',
    'authing_user': 'data.authing.authing_user.AuthingUser',
    'version_download': 'data.combine.version_download.VersionDownload',
    'software_repo_maintain': 'data.combine.software_repo_maintain.SoftwareRepoMaintain',
    'event_log_v8': 'data.event_log_v8.EventLogV8',
    'gitee_sla': 'data.gitee_sla.GiteeSLA',
    'gitee_filter': 'data.gitee_filter.GiteeFilter',
    'download_data': 'data.modelers.download.DownloadData',
    'model_download_compute': 'data.combine.model_download_compute.DownloadCompute',
    'image_download': 'data.combine.image_download.ImageDownload',
    'model_ci': 'data.modelers.model_ci.ModelCi',
    'file_moderation': 'data.modelers.file_moderation.FileModeration',
    'xihe_operation_log': 'data.xihe_operation_log.XiheOperationLog',
    'gitcode_user_info': 'data.gitcode_user_info.GitcodeUserInfo',
}


class George:

    def __init__(self):
        """ config is a Config object """
        self.config = ConfigParser()
        self.config.read('config.ini', 'UTF-8')
        self.sections = self.config.sections()
        self.from_data = self.config.get('general', 'from_data')
        self.sleep_time = self.config.getint('general', 'sleep_time')
        self.delete_config('config.ini')

    def start(self):
        logger.info("----------------------------")
        logger.info("Starting engine ...")
        logger.info("- - - - - - - - - - - - - - - ")

        drivers = []
        for backend in self.sections:
            if backend in BACKEND_MAPPING:
                driver = import_object(BACKEND_MAPPING[backend], self.getBackendConfig(backend))
                drivers.append(driver)

        starTime = self.from_data
        while True:
            if starTime is None:
                print("[common] Start to run from itself time")
            else:
                print("[common] Start to run from ", starTime)
            for driver in drivers:
                driver.run(starTime)

            print("try to run again....waiting for %d seconds, from %s" % (self.sleep_time, self.from_data))
            time.sleep(self.sleep_time)
            starTime = None
            print("try to run again")

        logger.info("Finished engine ...")

    def getBackendConfig(self, backend_name):
        backend_conf = {}
        for key, value in self.config.items('general'):
            backend_conf[key] = value

        for key, value in self.config.items(backend_name):
            backend_conf[key] = value
        return backend_conf

    
    @staticmethod
    def delete_config(path='config.ini'):
        try:
            os.remove(path)
            print(f"文件 '{path}' 删除成功")
        except Exception as e:
            print(f"删除文件时出错: {path}", e)


