#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
meetings_pg 连接池刷新测试

测试场景：
1. refresh_pool 方法正确调用 engine.dispose()
2. run 方法在执行前调用 refresh_pool
"""
import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到路径
sys.path.append("../..")

from data.meetings_pg import PgClient, Meetings


class TestPgClientRefreshPool(unittest.TestCase):
    """PgClient 连接池刷新测试"""

    def test_refresh_pool_calls_engine_dispose(self):
        """测试 refresh_pool 正确调用 engine.dispose()"""
        config = {
            'pg_host': 'localhost',
            'pg_dbname': 'test',
            'pg_user': 'test',
            'pg_password': 'test'
        }

        with patch('data.meetings_pg.create_engine') as mock_create_engine, \
             patch('data.meetings_pg.Base.metadata.create_all'):
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine

            pg_client = PgClient(config)

            # 调用 refresh_pool
            pg_client.refresh_pool()

            # 验证 engine.dispose() 被调用
            mock_engine.dispose.assert_called_once()

    def test_refresh_pool_exists(self):
        """测试 refresh_pool 方法存在"""
        # 验证方法存在
        self.assertTrue(hasattr(PgClient, 'refresh_pool'))
        self.assertTrue(callable(PgClient.refresh_pool))


class TestMeetingsRunRefreshPool(unittest.TestCase):
    """Meetings.run 连接池刷新测试"""

    def test_run_calls_refresh_pool_before_fetch(self):
        """测试 run 方法在执行前调用 refresh_pool"""
        config = {
            'pg_host': 'localhost',
            'pg_dbname': 'test',
            'pg_user': 'test',
            'pg_password': 'test',
            'community': 'test_community',
            'meeting_host': 'http://test',
            'meeting_info_url': '/test',
            'meeting_user_url': '/test',
            'meeting_user': 'user',
            'meeting_password': 'pass'
        }

        with patch('data.meetings_pg.PgClient') as mock_pg_client_class, \
             patch('data.meetings_pg.MeetingApi'), \
             patch('data.meetings_pg.MeetingService'):
            mock_pg_client = MagicMock()
            mock_pg_client_class.return_value = mock_pg_client

            meetings = Meetings(config)

            # Mock fetch_meeting 方法
            meetings.fetch_meeting = Mock()

            # 调用 run
            meetings.run(None)

            # 验证 refresh_pool 被调用
            mock_pg_client.refresh_pool.assert_called_once()

            # 验证 fetch_meeting 被调用
            meetings.fetch_meeting.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()