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

from data.common import ESClient
from data import common
import datetime


class Meetings(object):

    def __init__(self, config=None):
        self.config = config
        self.org = config.get('org', '')
        self.target_es_url = config.get('target_es_url')
        self.target_authorization = config.get('target_authorization')
        self.index_name = config.get('index_name')
        self.esClient = ESClient(config)
        self.meetings_url = config.get('meetings_url')
        self.participants_url = config.get('participants_url')
        self.headers = {'Content-Type': 'application/json', 'Authorization': config.get('authorization')}
        self.use_headers = config.get('use_headers', 'true')
        self.query_token = config.get('query_token')
        self.page_size = config.get('page_size', 50)
        self.meeting_headers = {'Referer': config.get('referer')}

    def run(self, from_time):
        print("*** Meetings collection start ***")
        self.getGiteeId2Company()
        self.get_all_meetings()
        self.tagUserOrgChanged()

    def get_all_meetings(self):
        print('get all meetings start...')
        page = 0
        while True:
            page += 1
            params = {
                "token": self.query_token,
                "page": page,
                "size": self.page_size
            }
            res = self.esClient.request_get(url=self.meetings_url, headers=self.meeting_headers, params=params)
            if res.status_code != 200:
                print("Get all meeting status: ", res.status_code)
                break
            meeting_list = res.json().get("data")
            actions = ''
            for meeting in meeting_list:
                action = self.get_meeting_info(meeting)
                actions += action
            header = {
                "Content-Type": 'application/x-ndjson',
                'Authorization': self.target_authorization
            }
            self.esClient.safe_put_bulk(bulk_json=actions, header=header, url=self.target_es_url)
        print('get all meetings end...')

    def get_meeting_info(self, meeting):
        meet_date = datetime.datetime.strptime(meeting.get("end"), "%H:%M") - datetime.datetime.strptime(
            meeting.get("start"), "%H:%M")
        meeting["duration_time"] = int(meet_date.seconds)
        participants = self.get_participants_by_meet(meeting.get("mid"))
        if participants == -1:
            return ''
        tuple_sList = [tuple(d.items()) for d in participants.get("participants", [])]
        unique_list = list(set(tuple_sList))
        unique_dict = [dict(t) for t in unique_list]
        meeting["total_records"] = len(unique_dict)
        meeting["participants"] = unique_dict
        company = 'independent'
        if meeting['sponsor'] in self.esClient.giteeid_company_dict:
            company = self.esClient.giteeid_company_dict[meeting['sponsor']]
        meeting["tag_user_company"] = company
        action = common.getSingleAction(self.index_name, meeting['id'], meeting)
        return action

    def get_participants_by_meet(self, mid):
        url = self.participants_url + mid + "/?token=" + self.query_token
        res = self.esClient.request_get(url=url, headers=self.meeting_headers)
        if res.status_code != 200:
            if res.status_code == 401:
                print("token failed: %s,  mid: %s" % (res.status_code, mid))
                return -1
            elif res.status_code == 404:
                print("participants not found: %s,  mid: %s" % (res.status_code, mid))
                return {}
            else:
                print("Get participants failed: %s,  mid: %s" % (res.status_code, mid))
                return {}

        participants = res.json()
        return participants

    def getGiteeId2Company(self):
        dic = self.esClient.getOrgByGiteeID()
        self.esClient.giteeid_company_dict = dic[0]
        self.esClient.giteeid_company_change_dict = dic[1]

    def tagUserOrgChanged(self):
        if len(self.esClient.giteeid_company_change_dict) == 0:
            return

        for key, vMap in self.esClient.giteeid_company_change_dict.items():
            vMap.keys()
            times = sorted(vMap.keys())
            for i in range(1, len(times)):
                if i == 1:
                    startTime = '1990-01-01'
                else:
                    startTime = times[i - 1]
                if i == len(times):
                    endTime = '2222-01-01'
                else:
                    endTime = times[i]
                company = vMap.get(times[i - 1])

                query = '''{
                    "script": {
                        "source": "ctx._source['tag_user_company']='%s'"
                    },
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "range": {
                                        "create_time": {
                                            "gte": "%s",
                                            "lt": "%s"
                                        }
                                    }
                                },
                                {
                                    "term": {
                                        "sponsor.keyword": "%s"
                                    }
                                }
                            ]
                        }
                    }
                }''' % (company, startTime, endTime, key)
                self.esClient.updateByQuery(query=query.encode(encoding='UTF-8'))