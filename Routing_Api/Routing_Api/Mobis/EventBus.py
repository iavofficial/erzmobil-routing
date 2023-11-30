import pika
import os
import time
from _thread import start_new_thread
import logging
import threading
from functools import partial
import atexit

LOGGER = logging.getLogger('Mobis.EventBus')

HOST = os.environ.get('RABBITMQ_HOST','localhost')
USER = os.environ.get('RABBITMQ_USERNAME','guest')
PASS = os.environ.get('RABBITMQ_PASSWORD','guest')
VHOST = os.environ.get('RABBITMQ_VHOST','/').replace("'", "").replace('"','')

if VHOST.lower().startswith('c:'):
    VHOST = '/'

EXCHANGE = 'busnow_event_bus'

if HOST:
    credentials = pika.PlainCredentials(USER, PASS)
    parameters = pika.ConnectionParameters(host=HOST,
                                        virtual_host=VHOST,
                                        credentials=credentials,
                                        heartbeat=60,
                                        blocked_connection_timeout=300, # after this, a blocked connection is closed
                                        connection_attempts=(5*60)//5, # listen for 5 minutes, then throw an error
                                        retry_delay=5)

class Publisher():
    # from https://groups.google.com/forum/#!searchin/pika-python/publish$20async%7Csort:date/pika-python/ZsH924c22e0/R3-Sag2DAgAJ
    # Blocking publisher
    """
    A threaded publisher, which opens a connection to the RabbitMQ instance. Responsible for publishing messages
    and managing the connection (e.g., creating a channel before sending a message and closing it afterwards).
    """

    def __init__(self):
        self._connection = None
        self._parameters = parameters

        self._thread = None
        self._stopping = False

        # Automatically close the connection to RabbitMQ when the program exits
        atexit.register(self.close)

    def start(self):
        """ Starts a background thread that runs the `run_loop` method. """

        self._thread = threading.Thread(target=self.run_loop)
        self._thread.setDaemon(True)
        self._thread.start()
        LOGGER.debug("STARTING PUBLISHER")

    def run_loop(self):
        """
        Runs in the background thread and maintains a connection to the RabbitMQ broker.
        Probes whether the connection is closed at regular intervals and tries to reconnect if it is.
        Closes the connection, when the `close` method is called.
        """

        self._connection = self.connect()
        while not self._stopping:
            try:
                if self._connection.is_closed:
                    LOGGER.debug("RECONNECTING")
                    self._connection = self.connect()
                self._connection.sleep(10)
            except pika.exceptions.ConnectionClosed as e:
                LOGGER.warning("Connection was closed: %s", e)
            except Exception as e:
                LOGGER.warning("Error maintaing connection to rabbit: %s", e)
                if self._connection.is_open:
                    self._connection.close()
        self._connection.close()
        LOGGER.debug("DISCONNECTED")

    def connect(self):
        """ Creates a blocking connection to RabbitMQ based on the configured parameters. """

        return pika.BlockingConnection(parameters=self._parameters)

    def create_channel(self):
        """
        Creates a channel to an exchange. Channels cannot exist without connections. When a connection is closed, so are all channels on it.
        """

        return self._connection.channel()

    def close_channel(self, channel):
        channel.close()
        #LOGGER.debug("channel CLOSED")

    def publish(self, message, routing_key, exchange=EXCHANGE):
        """
        Creates a channel and ublishes a message to a RabbitMQ exchange with the given routing key.
        Adds a timeout to close the channel after the message is sent.

        Attributes:
            message (str): The message to be published.
            routing_key (str): The routing key for the message. Used by the exchange to determin which queue to route the message to.
            exchange (str): The exchange to use for publishing the message. Defaults to `EXCHANGE` (= busnow_event_bus).
        """

        channel = None
        try:
            channel = self.create_channel()
        except Exception as e:
            # try to reconnect
            LOGGER.error("No channel due to exception: %s", e)
            LOGGER.info("try to reconnect")
            self._connection = self.connect() 
            channel = self.create_channel()
        
        LOGGER.debug("channel CREATED")
        LOGGER.info(f'sending {routing_key} with body: {message}')
        channel.publish(exchange=exchange, routing_key=routing_key, body=message)
        LOGGER.debug("PUBLISHED")
        self._connection.add_timeout(0, partial(self.close_channel, channel))

    def close(self):
        """ Closes the connection to RabbitMQ and closes the running thread. """

        self._stopping = True
        LOGGER.debug("DISCONNECTING")
        # wait for background thread to close connection
        self._thread.join()

class UnthreadedPublisher():
    """
    An unthreaded publisher, which opens a connection to the RabbitMQ instance. Responsible for publishing messages
    and managing the connection (e.g., creating a channel before sending a message and closing it afterwards).
    """
    def connect(self):
        # print('UnthreadedPublisher')
        # print(parameters.blocked_connection_timeout)

        return pika.BlockingConnection(parameters=parameters)

    def create_channel(self):
        return self._connection.channel()

    def close_channel(self, channel):
        channel.close()

    def publish(self, message, routing_key, exchange=EXCHANGE):
        self._connection = self.connect()
        channel = self.create_channel()
        LOGGER.debug("channel CREATED")
        LOGGER.info(f'sending {routing_key} with body: {message}')
        channel.publish(exchange=exchange, routing_key=routing_key, body=message,
            properties=pika.BasicProperties(content_type='text/plain',
                                                         delivery_mode=1))
        LOGGER.debug("PUBLISHED")
        self._connection.add_timeout(0, partial(self.close_channel, channel))
        self._connection.close()

class Consumer():
    """ Consumes messages from a RabbitMQ queue. Includes a dictionary of routing keys to callback functions."""

    connection = None
    channel = None
    callbacks = dict()  # routing_key: callback_function

    def __init__(self, queue_name='Busnow.Routes.API.Model.Routes'):
        self.queue_name = queue_name
    
    def run(self):
        """ Starts a background thread that runs the `run_loop` method. """
        start_new_thread(self.run_loop, ())

    def setup(self):
        """ Opens a connection to RabbitMQ, creates a channel, an exchange, and a queue and binds the que of each routing key to the `EXCHANGE`. """
        # This throws an error if no rabbitmq variables were set
        # Wait for RabbitMQ
        try:
            LOGGER.info('Trying to connect consumer to %s...', parameters)
            self.connection = pika.BlockingConnection(parameters)
            LOGGER.info('Success!')
        except pika.exceptions.ConnectionClosed as err:
            LOGGER.error('failed with: %s', err, exc_info=True)
            raise err
        self.channel = self.connection.channel()
        self.channel.exchange_declare(exchange=EXCHANGE,
                                      exchange_type='direct')
        self.result = self.channel.queue_declare(self.queue_name, exclusive=False, durable=True)
        
        for key in self.callbacks:
            self.channel.queue_bind(routing_key=key,
                                    exchange=EXCHANGE,
                                    queue=self.queue_name)

    def tear_down(self):
        if self.channel and self.channel.is_open:
            self.channel.close()
        if self.connection and self.connection.is_open:
            self.connection.close()

    def register(self, routing_key, callback):
        """ Registers a given callback to a `routing_key`. """

        print('register()')
        print(routing_key)
        print(callback)
        self.callbacks[routing_key] = callback

    def run_loop(self):
        """
        Runs in the background thread, maintains a connection to the RabbitMQ broker and consumes incoming messages.
        """
        while True:
            try:
                print('self.setup() + self.channel.basic_consume()')
                print(self.queue_name)
                self.setup()
                self.channel.basic_consume(
                    consumer_callback=self._callback, queue=self.queue_name)
                print('basic_consume invoked')
                print('invoking start_consuming()')
                self.channel.start_consuming()
                print('start_consuming() returned!')
            except Exception as e:
                LOGGER.error('rabbitmq consumer had the following error: %s', e)
            finally:
                self.tear_down()
    
    def _callback(self, ch, method, properties, body):
        """ Invokes the callback function for the routing key from the message. """
        
        print('info: incoming message')
        print(method.routing_key)
        print(body)
        LOGGER.info("info: incoming message %s with body %s", method.routing_key, body)
        if method.routing_key not in self.callbacks:
            LOGGER.warning('%s not registered', method.routing_key)
        try:
            self.channel.basic_ack(delivery_tag=method.delivery_tag)
            self.callbacks[method.routing_key](ch, method, properties, body)
        except Exception as err:
            LOGGER.error('%s, key: %s', err, method.routing_key, extra={'body': body}, exc_info=True)
            
