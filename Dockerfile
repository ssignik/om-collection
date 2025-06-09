FROM openeuler/openeuler:22.03

MAINTAINER zhongjun <jun.zhongjun2@gmail.com>
ENV LOG_DIR /var/log/om

RUN mkdir -p /var/lib/om
RUN mkdir -p ${LOG_DIR}
WORKDIR /var/lib/om

COPY . /var/lib/om

RUN yum update -y \
    && yum install -y shadow wget git rsync

RUN groupadd -g 1001 user \
    && useradd -u 1001 -g user -s /bin/bash -m user

RUN wget https://repo.huaweicloud.com/python/3.9.20/Python-3.9.20.tgz \
    && tar -zxvf Python-3.9.20.tgz \
    && cd Python-3.9.20 \
    && yum install -y gcc gcc-c++ make python3-devel libffi-devel bzip2-devel zlib* openssl-devel make \
    && ./configure --prefix=/usr/local/python3 \
    && make && make install \
    && yum clean all

RUN cd /usr/bin \
    && rm -rf ./python3 \
    && ln -s /usr/local/python3/bin/python3 /usr/bin/python3 \
    && ln -s /usr/local/python3/bin/pip3 /usr/bin/pip3

RUN python3 -m pip install --upgrade pip \
    && pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip3 install -r requirements.txt \
    && pip3 install google-api-python-client \
    && pip3 install --upgrade oauth2client

RUN wget -P /var/lib/ https://github.com/AlDanial/cloc/releases/download/v1.94/cloc-1.94.tar.gz && \
    cd /var/lib/ && \
    tar -zxvf cloc-1.94.tar.gz

RUN wget https://github.com/huaweicloud/huaweicloud-sdk-python-obs/archive/v3.20.7.tar.gz && \
    tar -xvzf v3.20.7.tar.gz  && \
    cd huaweicloud-sdk-python-obs-3.20.7/src && python3 setup.py install

RUN wget https://github.com/huaweicloud/huaweicloud-sdk-python/archive/v1.0.24.tar.gz && \
    tar -xvzf v1.0.24.tar.gz && \
    cd huaweicloud-sdk-python-1.0.24  &&\
    pip3 install -r requirements.txt &&\
    python3 setup.py install

RUN chown -R user:user /var/lib/om

USER user
CMD python3 -u  george.py