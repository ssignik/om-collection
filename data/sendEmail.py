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

import smtplib
import email.mime.multipart
import email.mime.text
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import json


def send_email(smtp_host, smtp_port, sendAddr, password, recipientAddrs, subject='', content='', fileppt=''):
    '''
     smtp_host: 域名
     smtp_port: 端口
     sendAddr: 发送邮箱
     password: 密码
     recipientAddrs: 目标邮箱
     subject: 标题
     content: 内容
    '''
    msg = email.mime.multipart.MIMEMultipart()
    msg['from'] = sendAddr
    msg['to'] = recipientAddrs
    msg['subject'] = subject
    txt = email.mime.text.MIMEText(content, 'plain', 'utf-8')
    msg.attach(txt)

    # 附件
    if fileppt:
        part = MIMEApplication(open(fileppt, 'rb').read())
        part.add_header('Content-Disposition', 'attachment', filename=fileppt)  # 发送文件名
        msg.attach(part)

    try:
        smtpSSLClient = smtplib.SMTP_SSL(smtp_host, smtp_port)
        loginRes = smtpSSLClient.login(sendAddr, password)  # 登录smtp服务器
        print(f"登录结果：loginRes = {loginRes}")  # loginRes = (235, b'Authentication successful')
        if loginRes and loginRes[0] == 235:
            print(f"登录成功，code = {loginRes[0]}")
            smtpSSLClient.sendmail(sendAddr, recipientAddrs, str(msg))
            print(f"mail has been send successfully. message:{str(msg)}")
            smtpSSLClient.quit()
        else:
            print(f"登陆失败，code = {loginRes[0]}")
    except Exception as e:
        print(f"发送失败，Exception: e={e}")


if __name__ == "__main__":
    try:
        with open("D:\\pngurl.json", 'r') as fj:
            f = json.load(fj)
        subject = 'Python 测试邮件'
        content = '''这是一封来自 Python 编写的测试邮件。
        这是一封来自 Python 编写的测试邮件。这是一封来自 Python 编写的测试邮件。
        这是一封来自 Python 编写的测试邮件。 %s
        这是一封来自 Python 编写的测试邮件。%s
        ''' % ('ABCD', 'EFG')
        send = f['email']['senddefault']
        smtp = f['email']['smtpkey']
        fileppt = ''
        for emaildrs in f['email']['users']:
            send_email('smtp.163.com', 465, send, smtp, emaildrs, subject, content, fileppt)
            break
    except Exception as err:
        print(traceback.format_exc())
