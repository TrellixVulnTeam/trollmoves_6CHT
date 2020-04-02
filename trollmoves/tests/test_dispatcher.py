#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2019
#
# Author(s):
#
#   Martin Raspaud <martin.raspaud@smhi.se>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Test the dispatcher."""

import os
import shutil
import signal
import time
from datetime import datetime
from queue import Queue
from tempfile import NamedTemporaryFile, gettempdir
from threading import get_ident
from unittest.mock import Mock, patch, call

import yaml

from trollmoves.dispatcher import (
    Dispatcher, YAMLConfig, check_conditions, dispatch
)

test_yaml1 = """
target1:
  host: ftp://ftp.target1.com
  connection_parameters:
    connection_uptime: 20
  filepattern: '{platform_name}_{start_time:%Y%m%d%H%M}.{format}'
  directory: /input_data/{sensor}
  dispatch_configs:
    - topics:
        - /level2/viirs
        - /level2/avhrr
      conditions:
        # key matches metadata items or provides default
        - product: [green_snow, true_color]
          sensor: viirs
        - product: [green_snow, overview]
          sensor: avhrr
          # special section "except" for negating
          except:
            platform_name: NOAA-15
    - topics:
        - /level3/cloudtype
      directory: /input/cloud_products
      conditions:
        - area: omerc_bb
          # ' 122'.strip().isdigit() -> True
          daylight: '<30'
          coverage: '>50'
"""

test_yaml2 = test_yaml1 + """
target2:
  host: ssh://server.target2.com
  connection_parameters:
    ssh_key_filename: ~/.ssh/rsa_id.pub
  filepattern: 'sat_{start_time:%Y%m%d%H%M}_{platform_name}.{format}'
  directory: /satellite/{sensor}
  dispatch_configs:
    - topics:
        - /level2/viirs
        - /level2/avhrr
      conditions:
        # key matches metadata items or provides default
        - product: [green_snow, true_color]
          sensor: viirs
        - product: [green_snow, overview]
          sensor: avhrr
          # special section "except" for negating
          except:
            platform_name: NOAA-15
    - topics:
        - /level3/cloudtype
      directory: /input/cloud_products
      conditions:
        - area: omerc_bb
          # ' 122'.strip().isdigit() -> True
          daylight: '<30'
          coverage: '>50'
"""

test_yaml_ssh_scp = test_yaml2 + """
target3:
  host: scp://user@server.target2.com
  connection_parameters:
    ssh_key_filename: ~/.ssh/rsa_id.pub
  filepattern: 'sat_{start_time:%Y%m%d%H%M}_{platform_name}.{format}'
  directory: /satellite/{sensor}
  dispatch_configs:
    - topics:
        - /level2/viirs
"""


def test_config_reading():
    """Test reading the config."""
    with NamedTemporaryFile('w', delete=False) as the_file:
        fname = the_file.name
        try:
            with patch.object(YAMLConfig, 'read_config') as rc:
                assert rc.call_count == 0
                yconf = YAMLConfig(fname)
                time.sleep(.1)
                assert rc.call_count == 1
                the_file.write(test_yaml1)
                the_file.flush()
                the_file.close()
                time.sleep(.1)
                assert rc.call_count == 2
                signal.pthread_kill(get_ident(), signal.SIGUSR1)
                time.sleep(.1)
                assert rc.call_count == 3
                os.remove(fname)
                signal.pthread_kill(get_ident(), signal.SIGUSR1)
                time.sleep(.1)
                yconf.close()
        finally:
            yconf.close()
            try:
                os.remove(fname)
            except FileNotFoundError:
                pass

    expected = yaml.safe_load(test_yaml1)
    with NamedTemporaryFile('w', delete=False) as the_file:
        fname = the_file.name
        try:
            yconf = YAMLConfig(fname)
            time.sleep(.1)
            the_file.write(test_yaml1)
            the_file.flush()
            the_file.close()
            time.sleep(.1)
            assert yconf.config == expected
        finally:
            yconf.close()
            try:
                os.remove(fname)
            except FileNotFoundError:
                pass


def test_check_conditions():
    """Check condition checking."""
    config_item = yaml.safe_load("""
      topics:
        - /level2/viirs
        - /level2/avhrr
      conditions:
        # key matches metadata items or provides default
        - product: [green_snow, true_color]
          sensor: viirs
        - product: [green_snow, overview]
          sensor: avhrr
          # special section "except" for negating
          except:
            platform_name: NOAA-15
            product: [green_snow, cloudtop]""")
    msg = Mock()
    msg.data = {'sensor': 'viirs', 'product': 'green_snow', 'platform_name': 'NOAA-20'}
    assert check_conditions(msg, config_item) is True
    msg.data = {'sensor': 'viirs', 'product': 'overview', 'platform_name': 'NOAA-20'}
    assert check_conditions(msg, config_item) is False
    msg.data = {'sensor': 'avhrr', 'product': 'overview', 'platform_name': 'NOAA-19'}
    assert check_conditions(msg, config_item) is True
    # check negation
    msg.data = {'sensor': 'avhrr', 'product': 'green_snow', 'platform_name': 'NOAA-15'}
    assert check_conditions(msg, config_item) is False
    msg.data = {'sensor': 'avhrr', 'product': 'overview', 'platform_name': 'NOAA-15'}
    assert check_conditions(msg, config_item) is True
    # missing keys in the message data
    msg.data = {'product': 'overview', 'platform_name': 'NOAA-19'}
    assert check_conditions(msg, config_item) is False
    msg.data = {'sensor': 'avhrr', 'product': 'green_snow'}
    assert check_conditions(msg, config_item) is False

    # numerical values
    config_item = yaml.safe_load("""
      topics:
        - /level3/cloudtype
      directory: /input/cloud_products
      conditions:
        - area: omerc_bb
          # ' 122'.strip().isdigit() -> True
          daylight: '<30'
          coverage: '>50'""")
    msg = Mock()
    msg.data = {'daylight': 18.3, 'area': 'omerc_bb', 'coverage': '77.1'}
    assert check_conditions(msg, config_item) is True
    msg.data = {'daylight': 48.3, 'area': 'omerc_bb', 'coverage': '77.1'}
    assert check_conditions(msg, config_item) is False
    msg.data = {'daylight': 18.3, 'area': 'omerc_bb', 'coverage': '27.1'}
    assert check_conditions(msg, config_item) is False


def test_get_destinations():
    """Check getting destination urls."""
    with patch('trollmoves.dispatcher.DispatchConfig'):
        with NamedTemporaryFile('w') as the_file:
            fname = the_file.name
            dp = Dispatcher(fname)
            dp.config = yaml.safe_load(test_yaml1)
            msg = Mock()
            msg.subject = '/level2/viirs'
            msg.data = {'sensor': 'viirs', 'product': 'green_snow', 'platform_name': 'NOAA-20',
                        'start_time': datetime(2019, 9, 19, 9, 19), 'format': 'tif'}
            expected_url = 'ftp://ftp.target1.com/input_data/viirs/NOAA-20_201909190919.tif'
            expected_attrs = {'connection_uptime': 20}

            res = dp.get_destinations(msg)
            assert len(res) == 1
            url, attrs, client = res[0]
            assert url == expected_url
            assert attrs == expected_attrs
            assert client == "target1"

            dp.config = yaml.safe_load(test_yaml2)
            res = dp.get_destinations(msg)
            assert len(res) == 2


test_yaml_aliases_simple = """
target1:
  host: ftp://ftp.target1.com
  connection_parameters:
    connection_uptime: 20
  filepattern: '{platform_name}_{product}_{start_time:%Y%m%d%H%M}.{format}'
  directory: /input_data/{sensor}
  aliases:
    product:
      green_snow: gs
    variant:
      DR: direct_readout
  dispatch_configs:
    - topics:
        - /level2/viirs
"""

test_yaml_aliases_multiple = """
target1:
  host: ftp://ftp.target1.com
  connection_parameters:
    connection_uptime: 20
  filepattern: '{platform_name}_{product}_{start_time:%Y%m%d%H%M}.{format}'
  directory: /input_data/{product_dir}
  aliases:
    product:
      - _alias_name: product_dir
        green_snow: alternate_dir_for_green_snow
      - green_snow: gs
    variant:
      DR: direct_readout
  dispatch_configs:
    - topics:
        - /level2/viirs
"""


def test_get_destinations_with_aliases():
    """Check getting destination urls."""
    with patch('trollmoves.dispatcher.DispatchConfig'):
        with NamedTemporaryFile('w') as the_file:
            fname = the_file.name
            dp = Dispatcher(fname)
            dp.config = yaml.safe_load(test_yaml_aliases_simple)
            msg = Mock()
            msg.subject = '/level2/viirs'
            msg.data = {'sensor': 'viirs', 'product': 'green_snow', 'platform_name': 'NOAA-20',
                        'start_time': datetime(2019, 9, 19, 9, 19), 'format': 'tif'}
            expected_url = 'ftp://ftp.target1.com/input_data/viirs/NOAA-20_gs_201909190919.tif'
            expected_attrs = {'connection_uptime': 20}

            res = dp.get_destinations(msg)
            assert len(res) == 1
            url, attrs, client = res[0]
            assert url == expected_url
            assert attrs == expected_attrs
            assert client == "target1"

            dp.config = yaml.safe_load(test_yaml_aliases_multiple)
            res = dp.get_destinations(msg)
            expected_url = 'ftp://ftp.target1.com/input_data/alternate_dir_for_green_snow/NOAA-20_gs_201909190919.tif'
            url, attrs, client = res[0]
            assert url == expected_url
            assert attrs == expected_attrs
            assert client == "target1"

            dp.config = yaml.safe_load(test_yaml2)
            res = dp.get_destinations(msg)
            assert len(res) == 2


test_local = """
target3:
  host: ""
  filepattern: '{platform_name}_{start_time:%Y%m%d%H%M}.{format}'
  directory: """ + os.path.join(gettempdir(), 'dptest') + """
  subscribe_addresses:
    - tcp://127.0.0.1:40000
  nameserver: 127.0.0.1
  subscribe_services:
    - service_name_1
    - service_name_2

  dispatch_configs:
    - topics:
        - /level2/viirs
        - /level2/avhrr
      conditions:
        # key matches metadata items or provides default
        - product: [green_snow, true_color]
          sensor: viirs
        - product: [green_snow, overview]
          sensor: avhrr
          # special section "except" for negating
          except:
            platform_name: NOAA-15
    - topics:
        - /level3/cloudtype
      directory: /input/cloud_products
      conditions:
        - area: omerc_bb
          # ' 122'.strip().isdigit() -> True
          daylight: '<30'
          coverage: '>50'
    """


def test_dispatcher():
    """Test the dispatcher class."""
    dp = None
    try:
        dest_dir = os.path.join(gettempdir(), 'dptest')
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        with patch('trollmoves.dispatcher.ListenerContainer') as lc:
            queue = Queue()
            lc.return_value.output_queue = queue
            with NamedTemporaryFile('w', delete=False) as config_file:
                config_file_name = config_file.name
                config_file.write(test_local)
                config_file.flush()
                config_file.close()
                dp = Dispatcher(config_file_name)
                dp.start()
                dest_dir = os.path.join(gettempdir(), 'dptest')
                assert not os.path.exists(dest_dir)
                with NamedTemporaryFile('w') as test_file:
                    msg = Mock()
                    msg.type = 'file'
                    msg.subject = '/level2/viirs'
                    msg.data = {'sensor': 'viirs', 'product': 'green_snow', 'platform_name': 'NOAA-20',
                                'start_time': datetime(2019, 9, 19, 9, 19), 'format': 'tif',
                                'area': 'euron1',
                                'uri': test_file.name}
                    expected_file = os.path.join(dest_dir, 'NOAA-20_201909190919.tif')
                    queue.put(msg)
                    time.sleep(.1)
                    assert os.path.exists(expected_file)
            # Check that the listener config items are passed correctly
            lc.assert_called_once_with(
                addresses=['tcp://127.0.0.1:40000'],
                nameserver='127.0.0.1',
                services=['service_name_1', 'service_name_2'],
                topics={'/level3/cloudtype', '/level2/viirs', '/level2/avhrr'})
    finally:
        if dp is not None:
            dp.close()
        os.remove(expected_file)
        os.rmdir(dest_dir)
        os.remove(config_file_name)


def test_create_dest_url():
    """Test creation of destination URL."""
    dp = None
    try:
        with patch('trollmoves.dispatcher.ListenerContainer') as lc:
            queue = Queue()
            lc.return_value.output_queue = queue
            with NamedTemporaryFile('w', delete=False) as config_file:
                config_file_name = config_file.name
                config_file.write(test_yaml_ssh_scp)
                config_file.flush()
                config_file.close()
            config = yaml.safe_load(test_yaml_ssh_scp)
            dp = Dispatcher(config_file_name)
            msg = Mock()
            msg.subject = '/level2/viirs'
            msg.data = {'sensor': 'viirs', 'product': 'green_snow', 'platform_name': 'NOAA-20',
                        'start_time': datetime(2019, 9, 19, 9, 19), 'format': 'tif'}
            # SSH protocol, no username
            url, params, client = dp.create_dest_url(msg, 'target2',
                                                     config['target2'])
            expected_url = "ssh://server.target2.com/satellite/viirs/sat_201909190919_NOAA-20.tif"
            assert url == expected_url
            assert params == {'ssh_key_filename': '~/.ssh/rsa_id.pub'}
            assert client == "target2"

            # SCP protocolw with username
            url, params, client = dp.create_dest_url(msg, 'target3',
                                                     config['target3'])
            expected_url = "scp://user@server.target2.com/satellite/viirs/sat_201909190919_NOAA-20.tif"
            assert url == expected_url
            assert client == "target3"

    finally:
        if dp is not None:
            dp.close()
        os.remove(config_file_name)


test_yaml_pub = test_yaml2 + """
target3:
  host: scp://user@server.target2.com
  filepattern: 'sat_{start_time:%Y%m%d%H%M}_{platform_name}.{format}'
  directory: /satellite/{sensor}
  publish_topic: "/topic/{platform_name}"
  dispatch_configs:
    - topics:
        - /level2/viirs
"""
@patch('trollmoves.dispatcher.Message')
@patch('trollmoves.dispatcher.ListenerContainer')
@patch('trollmoves.dispatcher.NoisyPublisher')
def test_publisher(NoisyPublisher, ListenerContainer, Message):
    """Test the publisher is initialized."""
    pub = Mock()
    NoisyPublisher.return_value = pub
    try:
        with NamedTemporaryFile('w', delete=False) as config_file:
            config_file_name = config_file.name
            config_file.write(test_yaml_pub)
            config_file.flush()
            config_file.close()
            try:
                dp = Dispatcher(config_file_name)
                assert dp.publisher is None
                NoisyPublisher.assert_not_called()
            finally:
                if dp is not None:
                    dp.close()
            try:
                dp = Dispatcher(config_file_name, publish_nameservers=["asd"])
                assert dp.publisher is None
                NoisyPublisher.assert_not_called()
            finally:
                if dp is not None:
                    dp.close()
            try:
                dp = Dispatcher(config_file_name, publish_port=0)
                init_call = call("dispatcher", port=0, nameservers=None)
                assert init_call in NoisyPublisher.mock_calls
            finally:
                if dp is not None:
                    dp.close()
                dp.publisher.stop.assert_called()
            try:
                dp = Dispatcher(config_file_name, publish_port=40000)
                init_call = call("dispatcher", port=40000, nameservers=None)
                assert init_call in NoisyPublisher.mock_calls
            finally:
                if dp is not None:
                    dp.close()
                assert len(dp.publisher.stop.mock_calls) == 2
            try:
                dp = Dispatcher(config_file_name, publish_port=40000,
                                publish_nameservers=["asd"])

                assert dp.publisher is pub
                init_call = call("dispatcher", port=40000, nameservers=["asd"])
                assert init_call in NoisyPublisher.mock_calls

                msg = Mock(data={'uri': 'original_path',
                                 'platform_name': 'platform'})
                destinations = [['url1', 'params1', 'target2'],
                                ['url2', 'params2', 'target3']]
                success = {'target2': False, 'target3': True}
                dp._publish(msg, destinations, success)
                dp.publisher.send.assert_called_once()
                # The message topic has been composed and uri has been replaced
                msg_call = call('/topic/platform', 'file',
                                {'uri': 'url2', 'platform_name': 'platform'})
                assert msg_call in Message.mock_calls
            finally:
                if dp is not None:
                    dp.close()
                    dp.publisher.stop.assert_called()
    finally:
        os.remove(config_file_name)


@patch('trollmoves.dispatcher.move_it')
def test_dispatch(move_it):
    """Test dispatching."""
    with NamedTemporaryFile('w') as source_file:
        source_file_name = source_file.name
        # Flush the file so that os.path.exists() works
        source_file.flush()
        # Two successful dispatches
        destinations = [['url1', 'params1', 'target1'],
                        ['url2', 'params2', 'target2']]
        res = dispatch(source_file_name, destinations)
        assert len(move_it.mock_calls) == 2

        # Exception is raised because two clients have the same name
        destinations = [['url1', 'params1', 'target1'],
                        ['url2', 'params2', 'target1']]

        try:
            res = dispatch(source_file_name, destinations)
            assert 1 == 0
        except NotImplementedError:
            pass

        # One of the dispatches fail
        move_it.side_effect = [None, IOError('test')]
        destinations = [['url1', 'params1', 'target1'],
                        ['url2', 'params2', 'target2']]
        res = dispatch(source_file_name, destinations)
        assert res == {'target1': True, 'target2': False}
