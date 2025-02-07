# Copyright (c) 2018-2019, NVIDIA CORPORATION. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import ctypes
import logging.config
import os
import random
import subprocess
import sys
import time
from contextlib import contextmanager

import numpy as np
import torch
import torch.distributed as dist
import torch.nn.init as init
import torch.utils.collect_env
from mlperf_logging.mllog import constants
from mlperf_logging import mllog


mllogger = mllog.get_mllogger()

def log_start(*args, **kwargs):
    _log_print(mllogger.start, *args, **kwargs)
def log_end(*args, **kwargs):
    _log_print(mllogger.end, *args, **kwargs)
def log_event(*args, **kwargs):
    _log_print(mllogger.event, *args, **kwargs)
def _log_print(logger, *args, **kwargs):
    """
    Wrapper for MLPerf compliance logging calls.
    All arguments but 'sync' and 'log_all_ranks' are passed to
    mlperf_logging.mllog.
    If 'sync' is set to True then the wrapper will synchronize all distributed
    workers. 'sync' should be set to True for all compliance tags that require
    accurate timing (RUN_START, RUN_STOP etc.)
    If 'log_all_ranks' is set to True then all distributed workers will print
    logging message, if set to False then only worker with rank=0 will print
    the message.
    """
    if kwargs.pop('sync', False):
        barrier()
    if 'stack_offset' not in kwargs:
        kwargs['stack_offset'] = 3
    if 'value' not in kwargs:
        kwargs['value'] = None

    if kwargs.pop('log_all_ranks', False):
        log = True
    else:
        log = (get_rank() == 0)

    if log:
        logger(*args, **kwargs)


def mlperf_submission_log(benchmark):
    required_dist_init = ['RANK', 'WORLD_SIZE', 'MASTER_ADDR', 'MASTER_PORT']

    if all(var in os.environ for var in required_dist_init):
        torch.distributed.init_process_group(backend='nccl', init_method='env://')

    num_nodes = os.environ.get('SLURM_NNODES', 1)

    mllog.config(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'transformer.log'))
    mllogger = mllog.get_mllogger()
    mllogger.logger.propagate = False

    log_event(
        key=constants.SUBMISSION_BENCHMARK,
        value=benchmark,
        )

    log_event(
        key=constants.SUBMISSION_ORG,
        value='Fujitsu')

    log_event(
        key=constants.SUBMISSION_DIVISION,
        value='closed')

    log_event(
        key=constants.SUBMISSION_STATUS,
        value='onprem')

    log_event(
        key=constants.SUBMISSION_PLATFORM,
        value=f'1xGX2570M5')

def barrier():
    """
    Works as a temporary distributed barrier, currently pytorch
    doesn't implement barrier for NCCL backend.
    Calls all_reduce on dummy tensor and synchronizes with GPU.
    """
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        torch.distributed.all_reduce(torch.cuda.FloatTensor(1))
        torch.cuda.synchronize()


def get_rank():
    """
    Gets distributed rank or returns zero if distributed is not initialized.
    """
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        rank = torch.distributed.get_rank()
    else:
        rank = 0
    return rank

