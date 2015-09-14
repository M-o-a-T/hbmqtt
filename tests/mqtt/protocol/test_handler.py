# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
import unittest
import asyncio
import logging
from hbmqtt.plugins.manager import PluginManager
from hbmqtt.session import Session, OutgoingApplicationMessage, IncomingApplicationMessage
from hbmqtt.mqtt.protocol.handler import ProtocolHandler
from hbmqtt.adapters import StreamWriterAdapter, StreamReaderAdapter
from hbmqtt.mqtt.constants import *
from hbmqtt.mqtt.publish import PublishPacket
from hbmqtt.mqtt.puback import PubackPacket

formatter = "[%(asctime)s] %(name)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=formatter)
log = logging.getLogger(__name__)


def adapt(reader, writer):
    return StreamReaderAdapter(reader), StreamWriterAdapter(writer)


class ProtocolHandlerTest(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.plugin_manager = PluginManager("hbmqtt.test.plugins", context=None, loop=self.loop)

    def tearDown(self):
        self.loop.close()

    def test_init_handler(self):
        s = Session()
        handler = ProtocolHandler(s, self.plugin_manager, loop=self.loop)
        self.assertIs(handler.session, s)
        self.assertIs(handler._loop, self.loop)
        self.check_empty_waiters(handler)

    def test_start_stop(self):
        @asyncio.coroutine
        def server_mock(reader, writer):
            pass

        @asyncio.coroutine
        def test_coro():
            try:
                s = Session()
                reader, writer = yield from asyncio.open_connection('127.0.0.1', 8888, loop=self.loop)
                s.reader, s.writer = adapt(reader, writer)
                handler = ProtocolHandler(s, self.plugin_manager, loop=self.loop)
                yield from self.start_handler(handler, s)
                yield from self.stop_handler(handler, s)
                future.set_result(True)
            except AssertionError as ae:
                future.set_exception(ae)

        future = asyncio.Future(loop=self.loop)
        coro = asyncio.start_server(server_mock, '127.0.0.1', 8888, loop=self.loop)
        server = self.loop.run_until_complete(coro)
        self.loop.run_until_complete(test_coro())
        server.close()
        self.loop.run_until_complete(server.wait_closed())
        if future.exception():
            raise future.exception()

    def test_publish_qos0(self):
        @asyncio.coroutine
        def server_mock(reader, writer):
            packet = yield from PublishPacket.from_stream(reader)
            try:
                self.assertEquals(packet.topic_name, '/topic')
                self.assertEquals(packet.qos, QOS_0)
                self.assertIsNone(packet.packet_id)
            except AssertionError as ae:
                future.set_exception(ae)

        @asyncio.coroutine
        def test_coro():
            try:
                s = Session()
                reader, writer = yield from asyncio.open_connection('127.0.0.1', 8888, loop=self.loop)
                s.reader, s.writer = adapt(reader, writer)
                handler = ProtocolHandler(s, self.plugin_manager, loop=self.loop)
                yield from self.start_handler(handler, s)
                message = yield from handler.mqtt_publish('/topic', b'test_data', QOS_0, False)
                self.assertIsInstance(message, OutgoingApplicationMessage)
                self.assertIsNotNone(message.publish_packet)
                self.assertIsNone(message.puback_packet)
                self.assertIsNone(message.pubrec_packet)
                self.assertIsNone(message.pubrel_packet)
                self.assertIsNone(message.pubcomp_packet)
                yield from self.stop_handler(handler, s)
                future.set_result(True)
            except AssertionError as ae:
                future.set_exception(ae)

        future = asyncio.Future(loop=self.loop)
        coro = asyncio.start_server(server_mock, '127.0.0.1', 8888, loop=self.loop)
        server = self.loop.run_until_complete(coro)
        self.loop.run_until_complete(test_coro())
        server.close()
        self.loop.run_until_complete(server.wait_closed())
        if future.exception():
            raise future.exception()

    def test_publish_qos1(self):
        @asyncio.coroutine
        def server_mock(reader, writer):
            packet = yield from PublishPacket.from_stream(reader)
            try:
                self.assertEquals(packet.topic_name, '/topic')
                self.assertEquals(packet.qos, QOS_1)
                self.assertIsNotNone(packet.packet_id)
                self.assertIn(packet.packet_id, self.session.inflight_out)
                self.assertIn(packet.packet_id, self.handler._puback_waiters)
            except AssertionError as ae:
                future.set_exception(ae)
            puback = PubackPacket.build(packet.packet_id)
            yield from puback.to_stream(writer)

        @asyncio.coroutine
        def test_coro():
            try:
                reader, writer = yield from asyncio.open_connection('127.0.0.1', 8888, loop=self.loop)
                self.session.reader, self.session.writer = adapt(reader, writer)
                self.handler = ProtocolHandler(self.session, self.plugin_manager, loop=self.loop)
                yield from self.start_handler(self.handler, self.session)
                message = yield from self.handler.mqtt_publish('/topic', b'test_data', QOS_1, False)
                self.assertIsInstance(message, OutgoingApplicationMessage)
                self.assertIsNotNone(message.publish_packet)
                self.assertIsNotNone(message.puback_packet)
                self.assertIsNone(message.pubrec_packet)
                self.assertIsNone(message.pubrel_packet)
                self.assertIsNone(message.pubcomp_packet)
                yield from self.stop_handler(self.handler, self.session)
                if not future.done():
                    future.set_result(True)
            except AssertionError as ae:
                future.set_exception(ae)
        self.handler = None
        self.session = Session()
        future = asyncio.Future(loop=self.loop)

        coro = asyncio.start_server(server_mock, '127.0.0.1', 8888, loop=self.loop)
        server = self.loop.run_until_complete(coro)
        self.loop.run_until_complete(test_coro())
        server.close()
        self.loop.run_until_complete(server.wait_closed())
        if future.exception():
            raise future.exception()

    @asyncio.coroutine
    def start_handler(self, handler, session):
        yield from handler.start()
        self.assertTrue(handler._reader_ready)
        self.check_empty_waiters(handler)
        self.check_no_message(session)

    @asyncio.coroutine
    def stop_handler(self, handler, session):
        yield from handler.stop()
        self.assertTrue(handler._reader_stopped)
        self.check_empty_waiters(handler)
        self.check_no_message(session)

    def check_empty_waiters(self, handler):
        self.assertFalse(handler._puback_waiters)
        self.assertFalse(handler._pubrec_waiters)
        self.assertFalse(handler._pubrel_waiters)
        self.assertFalse(handler._pubcomp_waiters)

    def check_no_message(self, session):
        self.assertFalse(session.inflight_out)
        self.assertFalse(session.inflight_in)
        self.assertEquals(session.delivered_message_queue.qsize(), 0)
