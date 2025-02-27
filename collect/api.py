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
# Create: 2024/6/21
import threading

import requests


global_thread_info = threading.local()
retry_time = 3


def exception_handler(func):
    def warp(*args, **kwargs):
        global_thread_info.num = 0
        global_thread_info.retrystate = 0

        response = None
        while global_thread_info.num < retry_time and global_thread_info.retrystate == 0:
            try:
                global_thread_info.num += 1
                response = func(*args, **kwargs)
                global_thread_info.retrystate = 1
                break
            except requests.exceptions.RequestException as ex:
                print(f"Retry {global_thread_info.num} failed. Error: {ex}")
                if global_thread_info.num >= retry_time:
                    print("Max retries reached. Exiting.")
                    raise ex
            except Exception as e:
                print(f"Unexpected error: {e}")
                global_thread_info.retrystate = 1
                raise e
        return response
    return warp


@exception_handler
def request_url(url, payload=None, headers=None, method="GET", stream=False, verify=False, auth=None, timeout=60):
    if method == 'GET':
        response = requests.get(url, params=payload, headers=headers, stream=stream, auth=auth, verify=verify, timeout=timeout)
    else:
        response = requests.post(url, data=payload, headers=headers, stream=stream, verify=verify, auth=auth)
    return response
