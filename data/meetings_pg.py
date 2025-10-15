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
import requests
import base64
import pytz
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, DateTime, pool
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import sessionmaker, Session, declarative_base
import urllib3
urllib3.disable_warnings()

# ==========================
# 数据库连接管理 (Database Client)
# ==========================
class PgClient(object):
    def __init__(self, config):
        self.config = config
        self.pg_host = config.get('pg_host')
        self.pg_dbname = config.get('pg_dbname')
        self.pg_user = config.get('pg_user')
        self.pg_password = config.get('pg_password')

        # 构建连接字符串
        self.db_url = f"postgresql+psycopg2://{self.pg_user}:{self.pg_password}@{self.pg_host}/{self.pg_dbname}"

        # 初始化数据库引擎和会话工厂
        self.engine = create_engine(
              self.db_url,
              poolclass=pool.QueuePool,
              pool_size=5,
              max_overflow=2,
              pool_recycle=3600,  # 每小时重建连接，避免超时
              pool_pre_ping=True  # 自动检测断开连接
          )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_session(self):
        """
        return one new sqlalchemy session.
        """
        return self.SessionLocal()

# ==========================
# 数据库模型 (Model)
# ==========================
Base = declarative_base()

class DynamicTableMixin:
    """
    动态表名混入类，用于动态设置表名.
    """
    _table_name = None  # 默认表名

    @classmethod
    def set_tablename(cls, table_name):
        cls._table_name = table_name

    @declared_attr
    def __tablename__(cls):
        if cls._table_name is None:
            raise ValueError(f"Table name for {cls.__name__} has not been set.")
        return cls._table_name

def get_meeting_model(table_name):
    class MeetingInfo(Base, DynamicTableMixin):
        __tablename__ = table_name
        uuid = Column(String,primary_key=True,index=True)
        meeting_id = Column(String,nullable=False)
        sponsor = Column(String,nullable=False)
        sig_name = Column(String,nullable=False)
        community = Column(String,nullable=False)
        topic = Column(String,nullable=False)
        created_at = Column(String,nullable=False)
        start = Column(String,nullable=False)
        end = Column(String,nullable=False)
        etherpad = Column(String,nullable=False)
        email_list = Column(String)
        mid = Column(String)
        join_url = Column(String,nullable=False)
        agenda = Column(String)
        is_removed = Column(String,nullable=False)
        m_id = Column(String)
        platform = Column(String)

        @classmethod
        def from_json(cls, json_data: dict):
            # 动态生成主键 UUID
            uuid = f"{json_data['id']}_{json_data['community']}"
            # 返回 会议 对象
            return cls(
                uuid=uuid,
                meeting_id=json_data.get('id'),
                sponsor=json_data.get('sponsor'),
                sig_name=json_data.get('group_name'),
                community=json_data.get('community'),
                topic=json_data.get('topic'),
                created_at=datetime.strptime(json_data.get('date'), '%Y-%m-%d') if json_data.get('date') else None,
                start=json_data.get('start'),
                end=json_data.get('end'),
                etherpad=json_data.get('etherpad'),
                email_list=json_data.get('email_list'),
                mid=json_data.get('mid'),
                join_url=json_data.get('join_url'),
                agenda=json_data.get('agenda'),
                is_removed="1" if json_data.get('is_delete') is True else None ,
                m_id=json_data.get('m_id'),
                platform=json_data.get('platform')
            )
    return MeetingInfo

def get_participant_model(table_name):
    class Participants(Base, DynamicTableMixin):
        __tablename__ = table_name
        uuid = Column(String, primary_key=True, index=True)
        meeting_id = Column(String, nullable=False)
        user_name = Column(String, nullable=False)

        @classmethod
        def from_meeting(cls, meeting_id, user_name):
            # 动态生成主键 UUID
            uuid = f"{meeting_id}_{user_name}"
            # 返回 参会者对象
            return cls(
                uuid=uuid,
                meeting_id=meeting_id,
                user_name=user_name
            )
    return Participants
# ==========================
# 服务类 (Service)
# ==========================
class MeetingService:
    """
    会议服务类，负责处理与会议相关的业务逻辑.
    """
    def __init__(self, pg_client):
        self.pg_client = pg_client

    def bulk_upsert_meeting(self, meetings):
        """
        批量插入或更新会议数据.
        """
        with self.pg_client.get_session() as session:
            try:
                for meeting in meetings:
                    session.merge(meeting)
                # 提交事务
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"Error bulk upserting users: {e}")

    def bulk_upsert_participants(self, participants):
        """
        批量插入或更新参会者数据.
        """
        with self.pg_client.get_session() as session:
            try:
                for participant in participants:
                    session.merge(participant)
                # 提交事务
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"Error bulk upserting users: {e}")

# ==========================
# 第三方接口模拟 (ThirdPart)
# ==========================
class MeetingApi:
    """
    第三方接口客户端，用于获取会议数据
    """
    def __init__(self, config=None):
        self.config = config
        self.meeting_host = config.get('meeting_host')
        self.meeting_info_url = config.get('meeting_info_url')
        self.meeting_user_url = config.get('meeting_user_url')
        self.meeting_user = config.get('meeting_user')
        self.meeting_password = config.get('meeting_password')

    def encode_credentials(self, username, password):
        """Encode credentials to Base64 format suitable for HTTP Basic Authentication."""
        auth_string = f"{username}:{password}"
        encoded_auth_string = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        return encoded_auth_string

    def call_api(self, url):
        """
        调用第三方接口获取会议数据.
        """
        encoded_auth_string = self.encode_credentials(self.meeting_user, self.meeting_password)
        # 构建请求头
        headers = {
            'Authorization': f'Basic {encoded_auth_string}'
        }
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            return response.json()  # 假设返回的是 JSON 格式的订单数据
        else:
            raise Exception(f"Failed to fetch meetings: {response.status_code} - {response.text}")

    def fetch_meeting_list(self, date_str, community):
        url = f"{self.meeting_host}{self.meeting_info_url}?date={date_str}&community={community}"
        return self.call_api(url)

    def fetch_participants(self, meeting_id, community):
        url = f"{self.meeting_host}{self.meeting_user_url}/{meeting_id}?community={community}"
        return self.call_api(url)

# ==========================
# 业务逻辑 (Business Logic)
# =========================
class Meetings(object):
    def __init__(self, config=None):
        self.config = config
        self.community = config.get('community')
        self.tz = pytz.timezone('Asia/Shanghai')

        self.MeetingInfo = get_meeting_model(f"fact_{self.community.lower()}_meeting_info")
        self.Participants = get_participant_model(f"fact_{self.community.lower()}_meeting_participants")

        self.pg_client = PgClient(self.config)
        self.meeting_service = MeetingService(self.pg_client)
        self.meeting_api = MeetingApi(self.config)

    def run(self, from_time):
        print("*** Meetings collection start ***")
        self.fetch_meeting(from_time)

    def fetch_meeting(self, from_time=None):
        now = datetime.now(tz=self.tz)
        start_date = now
        if from_time is not None:
            start_date = datetime.strptime(from_time, '%Y%m%d').replace(tzinfo=self.tz)

        current_date = start_date
        while current_date <= now:
            date_str = current_date.strftime('%Y-%m-%d')
            meeting_json = self.meeting_api.fetch_meeting_list(date_str, self.community)
            meeting_arr = []
            if meeting_json.get('data', []):
                for obj in meeting_json['data']:
                    meeting = self.MeetingInfo.from_json(obj)
                    meeting_arr.append(meeting)
                self.meeting_service.bulk_upsert_meeting(meeting_arr)
            if meeting_arr:
                self.fetch_participants(meeting_arr)
            print(f"fetch {current_date} meeting info success! count: {len(meeting_arr)}")
            current_date += timedelta(days=1)

    def fetch_participants(self, meetings):
        participant_arr = []
        for meeting in meetings:
            if meeting.is_removed is None:
                participants_json = self.meeting_api.fetch_participants(meeting.meeting_id, meeting.community)
                if participants_json.get('data', []) :
                    for name in participants_json['data']:
                        participant = self.Participants.from_meeting(meeting.meeting_id, name)
                        participant_arr.append(participant)
                print(f"fetch meeting {meeting.meeting_id} participants success! count: {len(participant_arr)}")
        self.meeting_service.bulk_upsert_participants(participant_arr)