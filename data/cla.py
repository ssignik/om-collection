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
import json

from data.common import ESClient
from collect.cla import ClaClient

LINK = 'link'
CORPORATION = 'corporation-signing'
EMPLOYEE = 'employee-signing'
INDIVIDUAL = 'individual-signing'


class Cla(object):
    def __init__(self, config=None):
        self.config = config
        self.orgs = config.get('orgs')
        self.esClient = ESClient(config)
        self.claClient = ClaClient(config)
        self.api_url = self.claClient.api_url
        self.timeout = self.claClient.timeout
        self.index_name = config.get('index_name')
        self.index_name_corporation = config.get('index_name_corporation')
        self.claIds = self.esClient.getEsIds(self.index_name)
        self.corporationIds = self.esClient.getEsIds(self.index_name_corporation)
        self.company_location_index = config.get('company_location_index')
        self.token = config.get('token')

    def run(self, from_time):
        print("Collect CLA data: start")
        self.getClaIndiviualsSigning()
        self.getClaCorporationsSigning()
        print("Collect CLA data: finished")

        self.deleteByIds()

    def getClaCorporationsSigning(self):
        # first: get token
        headers = {'token': self.token}

        # second: get link
        params = {
            'platform': self.claClient.platform,
            'orgs': self.orgs.split(',')
        }
        link_url = f'{self.api_url}/{LINK}'
        link_infos = self.claClient.fetch_cla(url=link_url, method='get', headers=headers, params=params)
        link_id = ''
        for link_info in link_infos['data']:
            if link_info['org_id'] != self.orgs:
                continue
            link_id = link_info['link_id']

        # third: get corporation
        corporation_url = f'{self.api_url}/{CORPORATION}/{link_id}'
        corporation_infos = self.claClient.fetch_cla(url=corporation_url, method='get', headers=headers)
        corDict = []
        for corporation_info in corporation_infos['data']:
            if corporation_info['corporation_name'].strip() == '中国电信股份有限公司云计算分公司':
                corporation_info['corporation_name'] = '天翼云科技有限公司'
            signing_id = corporation_info['id']
            corporation_name = corporation_info['corporation_name'].strip()
            admin_name = corporation_info['admin_name']
            admin_added = corporation_info['admin_added']
            pdf_uploaded = corporation_info['pdf_uploaded']
            if admin_added:
                admin_added = 1
            else:
                admin_added = 0
            if pdf_uploaded:
                pdf_uploaded = 1
            else:
                pdf_uploaded = 0

            # fourth: get users
            employee_url = f'{self.api_url}/{EMPLOYEE}/{link_id}/{signing_id}'
            employee_infos = self.claClient.fetch_cla(url=employee_url, method='get', headers=headers)
            employees = employee_infos['data']

            if len(employees) == 0:
                corDict.append((corporation_info, 0))
                continue
            corDict.append((corporation_info, 1))

            # write employees to es
            self.writeClaEmployees(corporation=corporation_name, admin_name=admin_name, admin_added=admin_added,
                                   pdf_uploaded=pdf_uploaded, employees=employees)

        # write corporations to es
        self.writeClaCorporation(corDict=corDict)

    def writeClaCorporation(self, corDict):
        if len(corDict) == 0:
            return

        actions = ""
        for corporation, is_there_employees in corDict:
            action = {
                "cla_language": corporation["cla_language"],
                "admin_email": corporation["admin_email"],
                "admin_name": corporation["admin_name"],
                "corporation_name": corporation['corporation_name'].strip(),
                "created_at": corporation['date'],
                "updated_at": corporation['date'],
                "admin_added": 1 if bool(corporation['admin_added']) else 0,
                "pdf_uploaded": 1 if bool(corporation['pdf_uploaded']) else 0,
                "is_there_employees": is_there_employees,
            }

            index_id = corporation['corporation_name'].strip() + corporation['admin_email']
            if index_id in self.corporationIds:
                self.corporationIds.remove(index_id)
            index_data = {"index": {"_index": self.index_name_corporation, "_id": index_id}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(action) + '\n'

        self.esClient.safe_put_bulk(actions)

    def writeClaEmployees(self, corporation, admin_name, admin_added, pdf_uploaded, employees):
        actions = ""
        for employee in employees:
            action = {
                "employee_id": employee["id"],
                "email": employee["email"],
                "name": employee["name"],
                "created_at": employee['date'],
                "updated_at": employee['date'],
                "corporation": corporation,
                "admin_name": admin_name,
                "is_admin_added": admin_added,
                "is_pdf_uploaded": pdf_uploaded,
                "is_corporation_signing": 1,
                "is_individual_signing": 0,
            }

            if employee['email'] in self.claIds:
                self.claIds.remove(employee['email'])
            if self.company_location_index:
                addr = self.esClient.getCompanyLocationInfo(corporation, self.company_location_index)
                if addr:
                    action.update(addr)
            index_data = {"index": {"_index": self.index_name, "_id": employee['email']}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(action) + '\n'

        self.esClient.safe_put_bulk(actions)

    def getClaIndiviualsSigning(self):
        # first: get token
        headers = {'token': self.token}

        # second: get link
        params = {
            'platform': self.claClient.platform,
            'orgs': self.orgs.split(',')
        }

        # second: get link
        link_url = f'{self.api_url}/{LINK}'
        link_infos = self.claClient.fetch_cla(url=link_url, method='get', headers=headers, params=params)
        link_id = ''
        for link_info in link_infos['data']:
            if link_info['org_id'] != self.orgs:
                continue
            link_id = link_info['link_id']

        # third: get individuals
        individual_url = f'{self.api_url}/{INDIVIDUAL}/{link_id}'
        individual_infos = self.claClient.fetch_cla(url=individual_url, method='get', headers=headers)
        individuals = individual_infos["data"]

        # write to es
        self.writeClaIndividuals(individuals)

    def writeClaIndividuals(self, individuals):
        actions = ""
        for individual in individuals:
            action = {
                "individual_id": individual["id"],
                "email": individual["email"],
                "name": individual["name"],
                "created_at": individual['date'],
                "is_corporation_signing": 0,
                "is_individual_signing": 1,
            }
            if individual.get('enabled'):
                action.update({"is_enabled": 1})

            if individual['email'] in self.claIds:
                self.claIds.remove(individual['email'])
            index_data = {"index": {"_index": self.index_name, "_id": individual['email']}}
            actions += json.dumps(index_data) + '\n'
            actions += json.dumps(action) + '\n'

        self.esClient.safe_put_bulk(actions)

    def deleteByIds(self):
        for id in self.claIds:
            self.esClient.deleteById(id=id, index_name=self.index_name)

        for id in self.corporationIds:
            self.esClient.deleteById(id=id, index_name=self.index_name_corporation)
